#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
import os
from urllib.parse import urlparse

import requests
from grafana_client import GrafanaApi # type: ignore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("grafana-api-logs-downloader")

class GrafanaApiLogDownloader:
    def __init__(
        self,
        grafana_url: str,
        api_key: str = "",
        username: str = "",
        password: str = "",
        verify_ssl: bool = True,
        organization_id: int = 1
    ):
        """Initialize Grafana logs downloader using the official Grafana API client

        Args:
            grafana_url: Base URL of the Grafana instance (e.g., https://grafana.example.com)
            api_key: Grafana API key (optional)
            username: Grafana username (if not using API key)
            password: Grafana password (if not using API key)
            verify_ssl: Whether to verify SSL certificates
            organization_id: Grafana organization ID
        """
        self.grafana_url = grafana_url.rstrip('/')
        self.verify_ssl = verify_ssl
        
        # Parse URL to get host and protocol
        parsed_url = urlparse(grafana_url)
        host = parsed_url.netloc
        protocol = parsed_url.scheme
        
        # Initialize the Grafana API client
        auth: Union[str, Tuple[str, str], None] = None
        if api_key:
            auth = api_key
        elif username and password:
            auth = (username, password)
            
        self.client = GrafanaApi(
            auth=auth,
            host=host,
            protocol=protocol,
            verify=verify_ssl,
            organization_id=organization_id
        )
        
        logger.info(f"Initialized Grafana API client for {grafana_url}")

    def check_connection(self) -> bool:
        """Check if we can connect to Grafana"""
        try:
            # Try to get the health status
            health = self.client.health.check()
            logger.info(f"Grafana health check: {health}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Grafana: {str(e)}")
            return False

    def get_datasources(self) -> List[Dict]:
        """Get all data sources from Grafana"""
        return self.client.datasource.list()

    def get_datasource_by_uid(self, uid: str) -> Dict:
        """Get details for a specific data source by UID"""
        return self.client.datasource.get_by_uid(uid)

    def get_datasource_id_from_uid(self, uid: str) -> Union[int, str]:
        """Get the numeric ID of a datasource from its UID"""
        try:
            datasource = self.get_datasource_by_uid(uid)
            datasource_id = datasource.get("id")
            if datasource_id is None:
                raise ValueError(f"Datasource with UID {uid} does not have an ID")
            return datasource_id
        except Exception as e:
            logger.error(f"Error getting datasource ID from UID: {str(e)}")
            # If we can't get the ID, try to use the UID as a fallback
            # This might work if the UID is actually a numeric ID
            try:
                return int(uid)
            except ValueError:
                # Return the UID as a string if we can't convert it to an int
                return uid

    def get_dashboard(self, dashboard_uid: str) -> Dict:
        """Get a dashboard by UID"""
        return self.client.dashboard.get_dashboard(dashboard_uid)
        
    def extract_dashboard_uid_from_url(self, dashboard_url: str) -> str:
        """Extract dashboard UID from a Grafana dashboard URL"""
        # Example URL: http://170.187.154.203:8084/d/service_logs_dashboard/services-logs?orgId=1
        # We need to extract 'service_logs_dashboard'
        parsed_url = urlparse(dashboard_url)
        path_parts = parsed_url.path.strip('/').split('/')
        
        if len(path_parts) >= 2 and path_parts[0] == 'd':
            return path_parts[1]
        
        raise ValueError(f"Could not extract dashboard UID from URL: {dashboard_url}")
        
    def get_dashboard_from_url(self, dashboard_url: str) -> Dict:
        """Get a dashboard from its URL"""
        dashboard_uid = self.extract_dashboard_uid_from_url(dashboard_url)
        logger.info(f"Extracted dashboard UID: {dashboard_uid}")
        return self.get_dashboard(dashboard_uid)
    
    def get_panels_from_dashboard(self, dashboard: Dict) -> List[Dict]:
        """Extract panels from a dashboard"""
        dashboard_data = dashboard.get("dashboard", {})
        panels = dashboard_data.get("panels", [])
        
        # Also check for rows that contain panels
        for row in dashboard_data.get("rows", []):
            if "panels" in row:
                panels.extend(row.get("panels", []))
                
        return panels
        
    def get_logs_panels_from_dashboard(self, dashboard: Dict) -> List[Dict]:
        """Extract only logs panels from a dashboard"""
        panels = self.get_panels_from_dashboard(dashboard)
        return [panel for panel in panels if panel.get("type") == "logs"]

    def query_loki_datasource(
        self,
        datasource_uid: str,
        query: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
        direction: str = "BACKWARD",
        instance_value: str = ""
    ) -> List[Dict]:
        """
        Query Loki logs through Grafana API
        
        Args:
            datasource_uid: UID of the Loki datasource
            query: LogQL query (e.g., '{instance="$instance", container_name="execution"}')
            start_time: Start time for the query
            end_time: End time for the query
            limit: Maximum number of log lines to retrieve
            direction: Query direction, either "BACKWARD" or "FORWARD"
            instance_value: Value to replace $instance variable in query
            
        Returns:
            List of log entries
        """
        # Replace variables with user-provided values
        if '$instance' in query:
            if instance_value:
                query = query.replace('$instance', instance_value)
            else:
                # If instance_value is empty, remove the instance label completely
                query = query.replace('instance="$instance", ', '')
                query = query.replace('instance="$instance"', '')
        
        # Clean up any empty filter expressions
        if '|= ``' in query:
            query = query.replace('|= ``', '')
            
        # Trim any extra whitespace
        query = query.strip()
        
        logger.info(f"Prepared query: {query}")
        
        # Convert timestamps to seconds for Loki
        start_sec = int(start_time.timestamp())
        end_sec = int(end_time.timestamp())
        
        try:
            # Use the built-in query_range method from the grafana-client library
            logger.info(f"Querying Loki datasource {datasource_uid} with query: {query}")
            
            # Prepare parameters for the query
            params = {
                "query": query,
                "start": start_sec,
                "end": end_sec,
                "limit": limit,
                "direction": direction
            }
            
            logger.info(f"Query parameters: {params}")
            
            # Use the datasource query_range method
            try:
                # First try with the UID
                response = self.client.datasource.query_range(
                    uid=datasource_uid,
                    **params
                )
            except Exception as e:
                logger.warning(f"Failed to query with UID, trying with name: {str(e)}")
                # If UID fails, try with the name (some versions of Grafana API require name instead of UID)
                response = self.client.datasource.query_range(
                    name=datasource_uid,
                    **params
                )
            
            logger.debug(f"Response: {response}")
            
            # Process the response
            logs = []
            if "data" in response and "result" in response["data"]:
                for stream in response["data"]["result"]:
                    stream_labels = stream.get("stream", {})
                    for entry in stream.get("values", []):
                        timestamp, log_line = entry
                        logs.append({
                            "timestamp": timestamp,
                            "datetime": datetime.fromtimestamp(float(timestamp) / 1e9).isoformat(),
                            "labels": stream_labels,
                            "log": log_line
                        })
                
                # Sort logs by timestamp
                logs.sort(key=lambda x: x["timestamp"], reverse=(direction == "BACKWARD"))
                
            return logs
            
        except Exception as e:
            logger.error(f"Error querying Loki: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response content: {e.response.text[:500]}")
            
            # Try an alternative approach if the built-in method fails
            logger.info("Trying alternative approach with direct HTTP request...")
            return self._query_loki_direct(
                datasource_uid=datasource_uid,
                query=query,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                direction=direction
            )
    
    def _query_loki_direct(
        self,
        datasource_uid: str,
        query: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
        direction: str = "BACKWARD"
    ) -> List[Dict]:
        """
        Fallback method to query Loki directly using HTTP requests
        """
        # Try to get the datasource URL from Grafana
        datasource_url = None
        try:
            datasources = self.client.datasource.list_datasources()
            for ds in datasources:
                if ds['uid'] == datasource_uid:
                    datasource_url = ds['url'].rstrip('/')
                    logger.info(f"Found datasource URL: {datasource_url}")
                    break
        except Exception as e:
            logger.warning(f"Could not get datasource URL: {str(e)}")
        
        # If we couldn't get the datasource URL, use the Grafana URL as fallback
        if not datasource_url:
            datasource_url = self.grafana_url
            logger.warning(f"Using Grafana URL as fallback: {datasource_url}")
        
        # Convert timestamps to string format for Loki
        start_str = str(int(start_time.timestamp()))
        end_str = str(int(end_time.timestamp()))
        
        # Prepare query parameters
        params = {
            "query": query,
            "start": start_str,
            "end": end_str,
            "limit": str(limit),
            "direction": direction
        }
        
        logger.info(f"Direct Loki query with params: {params}")
        
        # Try multiple approaches to connect to Loki
        errors = []
        
        # We'll try the Grafana proxy first as it's more likely to work
        try:
            # Get datasource ID from UID
            datasources = self.client.datasource.list_datasources()
            datasource_id = None
            for ds in datasources:
                if ds['uid'] == datasource_uid:
                    datasource_id = ds['id']
                    break
            
            if datasource_id is None:
                raise ValueError(f"Could not find datasource ID for UID {datasource_uid}")
            
            proxy_url = f"{self.grafana_url}/api/datasources/proxy/{datasource_id}/loki/api/v1/query_range"
            logger.info(f"Trying Grafana proxy URL with ID: {proxy_url}")
            
            response = requests.get(
                proxy_url,
                params=params,
                timeout=15  # Increased timeout
            )
            response.raise_for_status()
            return self._process_loki_response(response.json())
        except Exception as e:
            error_msg = f"Error with Grafana proxy: {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)
        
        # If proxy fails, try direct URL from datasource
        try:
            loki_query_url = f"{datasource_url}/loki/api/v1/query_range"
            logger.info(f"Trying direct URL: {loki_query_url}")
            response = requests.get(
                loki_query_url,
                params=params,
                timeout=15  # Increased timeout
            )
            response.raise_for_status()
            return self._process_loki_response(response.json())
        except Exception as e:
            error_msg = f"Error with direct URL: {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)
        
        # Try Loki on the same host as Grafana
        try:
            # Extract host from Grafana URL
            parsed_url = urlparse(self.grafana_url)
            loki_url = f"{parsed_url.scheme}://{parsed_url.netloc.split(':')[0]}:3100/loki/api/v1/query_range"
            logger.info(f"Trying Loki on same host: {loki_url}")
            
            response = requests.get(
                loki_url,
                params=params,
                timeout=15  # Increased timeout
            )
            response.raise_for_status()
            return self._process_loki_response(response.json())
        except Exception as e:
            error_msg = f"Error with Loki on same host: {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)
        
        # If all approaches fail, raise an exception
        raise RuntimeError(f"All approaches to connect to Loki failed: {errors}")
    
    def _process_loki_response(self, response_data: Dict) -> List[Dict]:
        """Process Loki response data into a list of log entries."""
        if 'data' not in response_data or 'result' not in response_data['data']:
            logger.error(f"Unexpected response format: {response_data}")
            return []
        
        log_entries = []
        
        for stream in response_data['data']['result']:
            labels = stream.get('stream', {})
            for entry in stream.get('values', []):
                timestamp, log_line = entry
                log_entries.append({
                    'timestamp': timestamp,
                    'datetime': datetime.fromtimestamp(float(timestamp) / 1e9).isoformat(),
                    'labels': labels,
                    'log': log_line
                })
        
        # Sort by timestamp (newest first)
        log_entries.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return log_entries

    def download_logs_from_panel(
        self, 
        panel_config: Dict,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        output_file: Optional[str] = None,
        format: str = "json",
        instance_value: str = "",
        limit: int = 1000,
        direction: str = "BACKWARD"
    ) -> List[Dict]:
        """
        Download logs using a panel configuration
        
        Args:
            panel_config: Grafana panel configuration
            start_time: Start time (defaults to 1 hour ago)
            end_time: End time (defaults to now)
            output_file: File to save logs to
            format: Output format (json or txt)
            instance_value: Value to replace $instance variable in query
            limit: Maximum number of log lines to retrieve
            direction: Query direction (BACKWARD or FORWARD)
            
        Returns:
            List of log entries
        """
        if not start_time:
            start_time = datetime.now() - timedelta(hours=1)
        if not end_time:
            end_time = datetime.now()
            
        # Get datasource UID from panel config - handle different panel structures
        datasource = panel_config.get("datasource", {})
        datasource_uid = None
        
        # Try different ways to extract datasource UID
        if isinstance(datasource, str):
            datasource_uid = datasource
        elif isinstance(datasource, dict):
            datasource_uid = datasource.get("uid")
        
        # If not found in main panel, check targets
        if not datasource_uid and "targets" in panel_config and panel_config["targets"]:
            target_ds = panel_config["targets"][0].get("datasource")
            if isinstance(target_ds, dict):
                datasource_uid = target_ds.get("uid")
            elif isinstance(target_ds, str):
                datasource_uid = target_ds
        
        if not datasource_uid:
            raise ValueError("No datasource UID found in panel configuration")
            
        # Extract query from panel targets - handle different panel structures
        targets = panel_config.get("targets", [])
        if not targets:
            raise ValueError("No targets found in panel configuration")
        
        # Get the first target's query
        target = targets[0]
        expr = None
        
        # Try different field names for the query
        for field in ["expr", "query", "expression"]:
            if field in target:
                expr = target[field]
                break
                
        if not expr:
            raise ValueError("No query expression found in panel target")
        
        logger.info(f"Extracted datasource UID: {datasource_uid}")
        logger.info(f"Extracted query: {expr}")
        
        # Get logs
        logs = self.query_loki_datasource(
            datasource_uid=datasource_uid,
            query=expr,
            start_time=start_time,
            end_time=end_time,
            instance_value=instance_value,
            limit=limit,
            direction=direction
        )
        
        # Save logs if output file is specified
        if output_file and logs:
            self._save_logs(logs, output_file, format)
            
        return logs
        
    def _save_logs(self, logs: List[Dict], output_file: str, format: str = "json"):
        """Save logs to a file"""
        if format.lower() == "json":
            with open(output_file, "w") as f:
                json.dump(logs, f, indent=2)
        elif format.lower() == "txt":
            with open(output_file, "w") as f:
                for log in logs:
                    f.write(f"{log['datetime']} | {log['log']}\n")
        else:
            raise ValueError(f"Unsupported format: {format}")
            
        logger.info(f"Saved {len(logs)} log entries to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Download logs from Grafana Loki using the official Grafana API")
    parser.add_argument(
        "--grafana-url",
        help="Grafana base URL (e.g., https://grafana.example.com)"
    )
    parser.add_argument(
        "--dashboard-url",
        help="Full Grafana dashboard URL (alternative to grafana-url)"
    )
    parser.add_argument(
        "--panel-index",
        type=int,
        default=0,
        help="Index of the logs panel to use when using dashboard-url (default: 0, first logs panel)"
    )
    parser.add_argument(
        "--api-key",
        help="Grafana API key (alternatively, use username/password)"
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
        "--panel-file",
        help="JSON file containing panel configuration"
    )
    parser.add_argument(
        "--panel-json",
        help="JSON string containing panel configuration"
    )
    parser.add_argument(
        "--datasource-uid",
        help="Loki datasource UID (if not using panel config)"
    )
    parser.add_argument(
        "--query",
        help="LogQL query (if not using panel config)"
    )
    parser.add_argument(
        "--start-time",
        help="Start time (ISO format or relative like '1h' for 1 hour ago)"
    )
    parser.add_argument(
        "--end-time",
        help="End time (ISO format or relative like '15m' for 15 minutes ago)"
    )
    parser.add_argument(
        "--output-file",
        help="Output file path"
    )
    parser.add_argument(
        "--format",
        choices=["json", "txt"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--instance",
        help="Value to replace $instance variable in queries"
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Check if we have either grafana-url or dashboard-url
    if not args.grafana_url and not args.dashboard_url:
        parser.error("Either --grafana-url or --dashboard-url must be provided")

    # Extract base URL from dashboard URL if provided
    if args.dashboard_url:
        parts = args.dashboard_url.split('/d/')
        if len(parts) != 2:
            logger.error(f"Invalid dashboard URL format: {args.dashboard_url}")
            sys.exit(1)
            
        args.grafana_url = parts[0]
        logger.info(f"Extracted Grafana base URL: {args.grafana_url}")

    # Process start and end times
    start_time = None
    end_time = None
    
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
                sys.exit(1)
        else:
            # Try parsing as ISO format
            try:
                start_time = datetime.fromisoformat(args.start_time)
            except ValueError:
                logger.error(f"Invalid start time format: {args.start_time}")
                sys.exit(1)
    
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
                sys.exit(1)
        else:
            # Try parsing as ISO format
            try:
                end_time = datetime.fromisoformat(args.end_time)
            except ValueError:
                logger.error(f"Invalid end time format: {args.end_time}")
                sys.exit(1)

    # Initialize downloader
    downloader = GrafanaApiLogDownloader(
        grafana_url=args.grafana_url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_ssl=not args.no_verify_ssl,
        organization_id=args.org_id
    )

    try:
        # Check connection to Grafana
        if not downloader.check_connection():
            logger.warning("Could not connect to Grafana. Proceeding anyway, but this may cause issues.")
        
        # Variable to store panel configuration
        panel_config = None
        
        # If dashboard URL is provided, use it to get panel configuration
        if args.dashboard_url:
            logger.info(f"Fetching dashboard from URL: {args.dashboard_url}")
            dashboard = downloader.get_dashboard_from_url(args.dashboard_url)
            logs_panels = downloader.get_logs_panels_from_dashboard(dashboard)
            
            if not logs_panels:
                logger.error("No logs panels found in the dashboard")
                sys.exit(1)
                
            if args.panel_index >= len(logs_panels):
                logger.error(f"Panel index {args.panel_index} out of range. Dashboard has {len(logs_panels)} logs panels.")
                sys.exit(1)
                
            # Use the selected panel as our configuration
            panel_config = logs_panels[args.panel_index]
            logger.info(f"Using panel: {panel_config.get('title', 'Unnamed panel')}")
        
        # If panel file is provided, use that for configuration
        elif args.panel_file:
            try:
                with open(args.panel_file, 'r') as f:
                    panel_config = json.load(f)
                logger.info(f"Loaded panel configuration from file: {args.panel_file}")
            except Exception as e:
                logger.error(f"Error loading panel configuration from file: {e}")
                sys.exit(1)
        
        # If panel JSON is provided, use that for configuration
        elif args.panel_json:
            try:
                panel_config = json.loads(args.panel_json)
                logger.info("Loaded panel configuration from JSON string")
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing panel JSON: {e}")
                sys.exit(1)
        
        # If panel configuration is provided, use it to download logs
        if panel_config:
            logger.info(f"Using panel configuration to download logs")
            logs = downloader.download_logs_from_panel(
                panel_config=panel_config,
                start_time=start_time,
                end_time=end_time,
                output_file=args.output_file,
                format=args.format,
                instance_value=args.instance or "",
                limit=1000,
                direction="BACKWARD"
            )
            logger.info(f"Downloaded {len(logs)} log entries")
        # Otherwise, use direct query if datasource and query are provided
        elif args.datasource_uid and args.query:
            logger.info(f"Using direct query to download logs")
            logs = downloader.query_loki_datasource(
                datasource_uid=args.datasource_uid,
                query=args.query,
                start_time=start_time or (datetime.now() - timedelta(hours=1)),
                end_time=end_time or datetime.now(),
                instance_value=args.instance or "",
                limit=1000,
                direction="BACKWARD"
            )
            
            if args.output_file and logs:
                downloader._save_logs(logs, args.output_file, args.format)
                
            logger.info(f"Downloaded {len(logs)} log entries")
        else:
            logger.error("Either panel configuration or datasource UID and query must be provided")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error downloading logs: {str(e)}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            logger.error(f"Response text: {e.response.text[:500]}")
        logger.error("Stack trace:", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 