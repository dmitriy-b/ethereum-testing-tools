#!/usr/bin/env python3
import os
import argparse
import json
from datetime import datetime, timedelta
import logging

from grafana_api_logs_downloader import GrafanaApiLogDownloader # type: ignore

"""
Universal script for downloading logs from any Grafana dashboard using the official Grafana API.
This script allows specifying all parameters via command line arguments.
"""

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("service-logs-api-downloader")

def main():
    parser = argparse.ArgumentParser(description="Download logs from any Grafana dashboard using Grafana API")
    # Basic parameters
    parser.add_argument(
        "--hours", 
        type=int,
        default=1,
        help="Hours of logs to retrieve (default: 1)"
    )
    parser.add_argument(
        "--service",
        default="execution",
        help="Service name to use in the container_name filter (default: execution)"
    )
    parser.add_argument(
        "--output",
        default="service_logs.json",
        help="Output file name (default: service_logs.json)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "txt"],
        default="json",
        help="Output format (default: json)"
    )
    
    # Grafana connection parameters
    parser.add_argument(
        "--grafana-url",
        required=True,
        help="Grafana base URL"
    )
    parser.add_argument(
        "--api-key",
        help="Grafana API key for authentication"
    )
    parser.add_argument(
        "--username",
        help="Grafana username (if not using API key)"
    )
    parser.add_argument(
        "--password",
        help="Grafana password (if not using API key)"
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL certificate verification"
    )
    parser.add_argument(
        "--org-id",
        type=int,
        default=1,
        help="Grafana organization ID (default: 1)"
    )
    
    # Datasource and query parameters
    parser.add_argument(
        "--datasource-uid",
        default="loki_ds_1",
        help="Loki datasource UID (default: loki_ds_1)"
    )
    parser.add_argument(
        "--query",
        help="Custom LogQL query (default: will be constructed based on service name)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of log lines to retrieve (default: 1000)"
    )
    parser.add_argument(
        "--direction",
        choices=["BACKWARD", "FORWARD"],
        default="BACKWARD",
        help="Query direction (default: BACKWARD - newest first)"
    )
    parser.add_argument(
        "--instance",
        help="Value to replace $instance variable in queries"
    )
    
    # Advanced options
    parser.add_argument(
        "--start-time",
        help="Explicit start time (ISO format or relative like '1h' for 1 hour ago)"
    )
    parser.add_argument(
        "--end-time",
        help="Explicit end time (ISO format or relative like '15m' for 15 minutes ago)"
    )
    parser.add_argument(
        "--dashboard-url",
        help="Full Grafana dashboard URL to extract panel from"
    )
    parser.add_argument(
        "--panel-index",
        type=int,
        default=0,
        help="Index of the logs panel to use when using dashboard-url (default: 0)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    # Process start and end times
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=args.hours)
    
    # Override with explicit times if provided
    if args.start_time:
        # Handle relative time strings (e.g., "1h" for 1 hour ago)
        if args.start_time.endswith(('s', 'm', 'h', 'd')):
            unit = args.start_time[-1]
            try:
                value = int(args.start_time[:-1])
                if unit == 's':
                    start_time = datetime.now() - timedelta(seconds=value)
                elif unit == 'm':
                    start_time = datetime.now() - timedelta(minutes=value)
                elif unit == 'h':
                    start_time = datetime.now() - timedelta(hours=value)
                elif unit == 'd':
                    start_time = datetime.now() - timedelta(days=value)
            except ValueError:
                logger.error(f"Invalid relative time format: {args.start_time}")
                return
        else:
            # Try parsing as ISO format
            try:
                start_time = datetime.fromisoformat(args.start_time)
            except ValueError:
                logger.error(f"Invalid start time format: {args.start_time}")
                return
    
    if args.end_time:
        # Handle relative time strings similar to start_time
        if args.end_time.endswith(('s', 'm', 'h', 'd')):
            unit = args.end_time[-1]
            try:
                value = int(args.end_time[:-1])
                if unit == 's':
                    end_time = datetime.now() - timedelta(seconds=value)
                elif unit == 'm':
                    end_time = datetime.now() - timedelta(minutes=value)
                elif unit == 'h':
                    end_time = datetime.now() - timedelta(hours=value)
                elif unit == 'd':
                    end_time = datetime.now() - timedelta(days=value)
            except ValueError:
                logger.error(f"Invalid relative time format: {args.end_time}")
                return
        else:
            # Try parsing as ISO format
            try:
                end_time = datetime.fromisoformat(args.end_time)
            except ValueError:
                logger.error(f"Invalid end time format: {args.end_time}")
                return
    
    # Initialize the downloader
    downloader = GrafanaApiLogDownloader(
        grafana_url=args.grafana_url,
        api_key=args.api_key or "",
        username=args.username or "",
        password=args.password or "",
        verify_ssl=not args.no_verify_ssl,
        organization_id=args.org_id
    )
    
    try:
        # Check connection to Grafana
        if not downloader.check_connection():
            logger.warning("Could not connect to Grafana. This may be due to authentication requirements.")
            logger.info("Proceeding anyway as the dashboard might be publicly accessible...")
        
        # If dashboard URL is provided, use it to get panel configuration
        if args.dashboard_url:
            logger.info(f"Fetching dashboard from URL: {args.dashboard_url}")
            dashboard = downloader.get_dashboard_from_url(args.dashboard_url)
            logs_panels = downloader.get_logs_panels_from_dashboard(dashboard)
            
            if not logs_panels:
                logger.error("No logs panels found in the dashboard")
                return
                
            if args.panel_index >= len(logs_panels):
                logger.error(f"Panel index {args.panel_index} out of range. Dashboard has {len(logs_panels)} logs panels.")
                return
                
            # Use the selected panel as our configuration
            panel_config = logs_panels[args.panel_index]
            logger.info(f"Using panel: {panel_config.get('title', 'Unnamed panel')}")
            
            # Download logs using the panel from the dashboard
            print(f"Fetching logs from dashboard panel for the past {args.hours} hour(s)...")
            logs = downloader.download_logs_from_panel(
                panel_config=panel_config,
                start_time=start_time,
                end_time=end_time,
                output_file=args.output,
                format=args.format,
                instance_value=args.instance or "",
                limit=args.limit,
                direction=args.direction
            )
            logger.info(f"Downloaded {len(logs)} log entries")
            
            if logs:
                print(f"Downloaded {len(logs)} log entries to {args.output}")
                
                # Print a preview of the first 5 logs
                print("\nPreview of downloaded logs:")
                for i, log in enumerate(logs[:5]):
                    print(f"{i+1}. {log['datetime']}: {log['log'][:100]}...")
                
                if len(logs) > 5:
                    print(f"... and {len(logs) - 5} more entries")
            else:
                print("No logs found matching the query")
                
        else:
            # Create a panel config based on command line arguments
            query = args.query if args.query else f"{{container_name=\"{args.service}\"}}"
            
            panel_config = {
                "datasource": {
                    "type": "loki",
                    "uid": args.datasource_uid
                },
                "targets": [
                    {
                        "datasource": {
                            "type": "loki",
                            "uid": args.datasource_uid
                        },
                        "expr": query,
                        "queryType": "range",
                        "refId": "A"
                    }
                ],
                "title": args.service.capitalize(),
                "type": "logs"
            }
            
            # Download logs using our constructed panel config
            if args.query:
                print(f"Fetching logs with custom query for the past {args.hours} hour(s)...")
            else:
                print(f"Fetching {args.service} logs for the past {args.hours} hour(s)...")
            logs = downloader.download_logs_from_panel(
                panel_config=panel_config,
                start_time=start_time,
                end_time=end_time,
                output_file=args.output,
                format=args.format,
                instance_value=args.instance or "",
                limit=args.limit,
                direction=args.direction
            )
            logger.info(f"Downloaded {len(logs)} log entries")
            
            if logs:
                print(f"Downloaded {len(logs)} log entries to {args.output}")
                
                # Print a preview of the first 5 logs
                print("\nPreview of downloaded logs:")
                for i, log in enumerate(logs[:5]):
                    print(f"{i+1}. {log['datetime']}: {log['log'][:100]}...")
                
                if len(logs) > 5:
                    print(f"... and {len(logs) - 5} more entries")
            else:
                print("No logs found matching the query")
                
    except Exception as e:
        print(f"Error: {str(e)}")
        if args.debug:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main() 