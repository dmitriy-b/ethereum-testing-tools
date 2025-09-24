#!/usr/bin/env python3
import argparse
import logging
import json
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

import slackweb

# Constants
REPORTS_DIR = "reports"
DEFAULT_VERDICT = "pass"
DEFAULT_DESCRIPTION = "Auto tests"
ARTIFACTS_DOWNLOAD_PATH = "#artifacts"
SLACK_COLORS = {
    "pass": "good",
    "fail": "warning"
}

def parse_arguments() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser(description='slack notification script')
    
    parser.add_argument('--webhook-url', help='incoming webhook url')
    parser.add_argument('--verdict', help='pass or fail', default=DEFAULT_VERDICT)
    parser.add_argument('--description', help='what report about', default=DEFAULT_DESCRIPTION)
    parser.add_argument('--version', help='build version')
    parser.add_argument('--report-link', help='report link')
    parser.add_argument('--summary', help='summary')
    parser.add_argument('--timestamp', help='timestamp')
    parser.add_argument('--pipeline-link', help='ci job link')
    parser.add_argument('--report-name', help='name of json file with test results')
    parser.add_argument('--text', help='Additional text before the message')
    parser.add_argument('--additional-info', help='any other additional information will display at footer')
    
    return parser.parse_args()

def create_attachment_fields(args: argparse.Namespace) -> List[Dict]:
    """Create attachment fields for Slack message based on provided arguments."""
    fields = []
    
    if args.description:
        fields.append({"title": "Description", "value": args.description, "short": False})
    
    if args.version:
        fields.append({"title": "version", "value": f"`{args.version}`", "short": True})
    
    if args.report_link:
        fields.append({"title": "artifacts", "value": f"(<{args.report_link} | download>)", "short": True})
    
    if args.pipeline_link:
        fields.append({"title": "pipeline", "value": f"(<{args.pipeline_link} | open>)", "short": True})
    
    if args.summary:
        fields.append({"title": "summary", "value": args.summary, "short": False})
    
    return fields

def get_footer_text(args: argparse.Namespace) -> Optional[str]:
    """Generate footer text from arguments."""
    footer_text = args.additional_info + "\n" if args.additional_info else ""
    if args.timestamp:
        footer_text += f"Tests started at: {args.timestamp}"
    return footer_text or None

def load_test_results(report_name: str) -> Dict:
    """Load and return test results from JSON file."""
    try:
        report_path = Path(REPORTS_DIR) / f"{report_name}.json"
        with open(report_path) as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Report file not found: {report_path}")
        raise
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in report file: {report_path}")
        raise

def get_failed_tests(data: Dict) -> List[str]:
    """Extract failed test names from test data."""
    return [x["nodeid"].split("::")[1] for x in data["tests"] if x["outcome"] == "failed"]

def notify() -> None:
    """Main function to send Slack notifications."""
    args = parse_arguments()
    
    attachment_fields = create_attachment_fields(args)
    footer_text = get_footer_text(args)

    try:
        slack = slackweb.Slack(url=args.webhook_url)
        attachments = [{
            "color": SLACK_COLORS[args.verdict],
            "fields": attachment_fields,
            "footer": footer_text,
        }]
        
        if args.text:
            slack.notify(text=args.text, attachments=attachments)
        else:
            slack.notify(attachments=attachments)
    except Exception as e:
        logging.error(f"Failed to send Slack notification: {str(e)}")
        raise

def send_to_slack(
    webhook_url: str,
    description: str,
    summary: Optional[str] = None,
    timestamp: Optional[str] = None,
    verdict: str = DEFAULT_VERDICT,
    post_only_failed: bool = True,
    job_url: Optional[str] = None,
    report_name: str = "report"
) -> None:
    """Send notification to slack channel with test results."""
    logging.info("Sending report to Slack channel ...")

    timestamp = timestamp or datetime.now().isoformat()
    additional_message = ""

    if not summary:
        data = load_test_results(report_name)
        summary = json.dumps(data["summary"])
        
        if "passed" not in data["summary"] or data["summary"]["passed"] < data["summary"]["total"] - data["summary"].get("skipped", 0):
            verdict = "fail"
            failed_tests = get_failed_tests(data)
            additional_message = "Failed tests: " + ", ".join(failed_tests)

    if not post_only_failed or verdict == "fail":
        # Create an argparse.Namespace object with all the required arguments
        args = argparse.Namespace(
            webhook_url=webhook_url,
            description=description,
            summary=summary,
            timestamp=timestamp,
            verdict=verdict,
            additional_info=additional_message,
            version=None,
            text=None,
            report_name=report_name,
            pipeline_link=job_url if job_url else None,
            report_link=f"{job_url}/{ARTIFACTS_DOWNLOAD_PATH}" if job_url else None
        )

        # Create Slack client and send notification
        slack = slackweb.Slack(url=args.webhook_url)
        attachment_fields = create_attachment_fields(args)
        footer_text = get_footer_text(args)

        attachments = [{
            "color": SLACK_COLORS[args.verdict],
            "fields": attachment_fields,
            "footer": footer_text,
        }]
        logging.info(f"Sending attachments: {attachments}")
        slack.notify(attachments=attachments)
    else:
        logging.warning("Skipped sending report to slack")

if __name__ == '__main__':
    notify()