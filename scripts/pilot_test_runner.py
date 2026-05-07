import json
import logging
import time
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Ensure we can import from the root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scheduler.task_scheduler import TaskScheduler
from workflows.review_queue import ReviewQueue
from agents.analytics_agent import AnalyticsAgent
from agents.learning_agent import LearningAgent

logger = logging.getLogger("signalforge.pilot")

class PilotTestRunner:
    """
    Wrapper for running the full SignalForge pipeline repeatedly 
    to validate stability, analytics, and persistent storage growth.
    """
    def __init__(self, query: str, number_of_runs: int = 3, frequency: str = "daily"):
        self.query = query
        self.number_of_runs = number_of_runs
        self.frequency = frequency
        
        # Core components
        self.scheduler = TaskScheduler()
        self.review_queue = ReviewQueue()
        self.analytics = AnalyticsAgent()
        self.learning = LearningAgent()
        
        # State tracking
        self.initial_queue_size = 0
        self.initial_analytics_count = 0
        self.results = []
        
        self.reports_dir = Path("outputs/pilot_reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _get_queue_size(self) -> int:
        return len([i for i in self.review_queue.items if i.get("review_status") == "pending"])

    def _get_analytics_count(self) -> int:
        # Analytics Agent has reports, but it writes to Supabase.
        # It has self.report which we can load.
        report = self.analytics.generate_report()
        return report.get("total_pipeline_volume", 0)

    def run(self) -> str:
        """Run the pilot test and return the path to the report."""
        logger.info("Starting Pilot Test for query '%s' (%d runs)", self.query, self.number_of_runs)
        
        # Capture baseline
        self.initial_queue_size = self._get_queue_size()
        self.initial_analytics_count = self._get_analytics_count()
        baseline_learning = self.learning.generate_recommendations()

        # Schedule the task
        task = self.scheduler.schedule_task(self.query, self.frequency)
        task_id = task["id"]
        logger.info("Scheduled pilot task: %s", task_id)
        
        success_count = 0
        failed_runs = []

        for i in range(1, self.number_of_runs + 1):
            logger.info("--- Pilot Run %d/%d ---", i, self.number_of_runs)
            
            # Load fresh task state
            tasks = self.scheduler.list_tasks()
            live_task = next((t for t in tasks if t["id"] == task_id), None)
            if not live_task:
                logger.error("Task %s vanished from storage!", task_id)
                failed_runs.append({"run": i, "error": "Task missing"})
                break
                
            if not live_task.get("active"):
                logger.warning("Task %s became inactive unexpectedly.", task_id)

            # Bypass time check and execute forcefully
            result = self.scheduler.run_scheduled_task(live_task)
            
            self.results.append(result)
            if result.get("success"):
                success_count += 1
                logger.info("Run %d successful.", i)
            else:
                logger.error("Run %d failed: %s", i, result.get("status"))
                failed_runs.append({"run": i, "status": result.get("status")})

            # Small delay to ensure Supabase updates flush and avoid rate limits
            time.sleep(2)

        # Post-run metrics
        final_queue_size = self._get_queue_size()
        final_analytics_count = self._get_analytics_count()
        final_learning = self.learning.generate_recommendations()
        
        items_created = final_queue_size - self.initial_queue_size
        events_created = final_analytics_count - self.initial_analytics_count
        
        # Report compilation
        report = {
            "timestamp": datetime.now().isoformat(),
            "query": self.query,
            "configured_runs": self.number_of_runs,
            "actual_runs": len(self.results),
            "success_rate": f"{(success_count / self.number_of_runs) * 100:.1f}%" if self.number_of_runs else "0%",
            "metrics": {
                "opportunities_discovered": items_created,  # Proxied by review queue growth
                "review_items_created": items_created,
                "analytics_events_created": events_created,
                "avg_opportunities_per_run": round(items_created / success_count, 1) if success_count else 0,
            },
            "learning_adjustments_observed": final_learning != baseline_learning,
            "baseline_learning": baseline_learning,
            "final_learning": final_learning,
            "failed_runs": failed_runs,
            "system_stability": "VERIFIED" if success_count == self.number_of_runs else "DEGRADED"
        }
        
        # Cleanup pilot task
        self.scheduler.cancel_task(task_id)
        
        # Save Report
        filename = f"pilot_report_{int(time.time())}.json"
        report_path = self.reports_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        logger.info("Pilot test complete. Report saved to %s", report_path)
        return str(report_path)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run SignalForge Pilot Test")
    parser.add_argument("--query", type=str, required=True, help="Query to run")
    parser.add_argument("--runs", type=int, default=3, help="Number of times to run")
    parser.add_argument("--frequency", type=str, default="daily", help="Task frequency")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    runner = PilotTestRunner(query=args.query, number_of_runs=args.runs, frequency=args.frequency)
    runner.run()
