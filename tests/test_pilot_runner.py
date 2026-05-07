import os
import sys
import json
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.pilot_test_runner import PilotTestRunner

@patch('scripts.pilot_test_runner.TaskScheduler')
@patch('scripts.pilot_test_runner.ReviewQueue')
@patch('scripts.pilot_test_runner.AnalyticsAgent')
@patch('scripts.pilot_test_runner.LearningAgent')
def test_pilot_runner_success(mock_learning, mock_analytics, mock_queue, mock_scheduler, tmp_path):
    # Setup mocks
    mock_sched_inst = mock_scheduler.return_value
    mock_sched_inst.schedule_task.return_value = {"id": "test-task"}
    mock_sched_inst.list_tasks.return_value = [{"id": "test-task", "active": True}]
    mock_sched_inst.run_scheduled_task.return_value = {"success": True, "status": "ok"}
    
    mock_queue_inst = mock_queue.return_value
    # Initial size 0, final size 2
    type(mock_queue_inst).items = PropertyMock(side_effect=[
        [], 
        [{"review_status": "pending"}, {"review_status": "pending"}]
    ])
    
    mock_analytics_inst = mock_analytics.return_value
    mock_analytics_inst.generate_report.side_effect = [{"total_pipeline_volume": 0}, {"total_pipeline_volume": 2}]
    
    mock_learning_inst = mock_learning.return_value
    mock_learning_inst.generate_recommendations.side_effect = [{"patterns": []}, {"patterns": ["new"]}]
    
    # Run test
    runner = PilotTestRunner(query="test", number_of_runs=2)
    runner.reports_dir = tmp_path
    
    report_path = runner.run()
    
    # Verify report generated
    assert os.path.exists(report_path)
    with open(report_path, 'r') as f:
        report = json.load(f)
        
    assert report["actual_runs"] == 2
    assert report["success_rate"] == "100.0%"
    assert report["metrics"]["opportunities_discovered"] == 2
    assert report["learning_adjustments_observed"] is True
    assert report["system_stability"] == "VERIFIED"

@patch('scripts.pilot_test_runner.TaskScheduler')
@patch('scripts.pilot_test_runner.ReviewQueue')
@patch('scripts.pilot_test_runner.AnalyticsAgent')
@patch('scripts.pilot_test_runner.LearningAgent')
def test_pilot_runner_failures(mock_learning, mock_analytics, mock_queue, mock_scheduler, tmp_path):
    mock_sched_inst = mock_scheduler.return_value
    mock_sched_inst.schedule_task.return_value = {"id": "test-task"}
    mock_sched_inst.list_tasks.return_value = [{"id": "test-task", "active": True}]
    # 1 success, 1 failure
    mock_sched_inst.run_scheduled_task.side_effect = [
        {"success": True, "status": "ok"},
        {"success": False, "status": "api_error"}
    ]
    
    mock_queue_inst = mock_queue.return_value
    type(mock_queue_inst).items = PropertyMock(return_value=[])
    
    mock_analytics_inst = mock_analytics.return_value
    mock_analytics_inst.generate_report.return_value = {"total_pipeline_volume": 0}
    
    mock_learning_inst = mock_learning.return_value
    mock_learning_inst.generate_recommendations.return_value = {"patterns": []}
    
    runner = PilotTestRunner(query="test", number_of_runs=2)
    runner.reports_dir = tmp_path
    report_path = runner.run()
    
    with open(report_path, 'r') as f:
        report = json.load(f)
        
    assert report["success_rate"] == "50.0%"
    assert len(report["failed_runs"]) == 1
    assert report["failed_runs"][0]["status"] == "api_error"
    assert report["system_stability"] == "DEGRADED"
