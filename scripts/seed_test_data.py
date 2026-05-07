import os
import sys

# Ensure SignalForge is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.analytics_agent import AnalyticsAgent
from agents.learning_agent import LearningAgent
from scheduler.task_scheduler import TaskScheduler

def seed_data():
    print("Seeding analytics event...")
    analytics = AnalyticsAgent()
    analytics.track_review({
        "review_id": "test-review-001",
        "opportunity": {"platform": "reddit"},
        "draft": {},
        "compliance": {},
        "intent": {"intent": "buying_intent"},
        "score": {"priority_score": 85}
    }, "approved")
    analytics.save_report()
    
    print("Seeding learning state...")
    learning = LearningAgent()
    learning.save_learning_state()
    
    print("Seeding scheduled task...")
    scheduler = TaskScheduler()
    scheduler.schedule_task("AI workflow automation pain points", "daily")

    print("Done seeding.")

if __name__ == "__main__":
    seed_data()
