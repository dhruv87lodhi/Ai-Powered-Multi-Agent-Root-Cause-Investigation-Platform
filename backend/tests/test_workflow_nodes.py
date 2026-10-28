# testing first node receive incident

from app.workflow.nodes import receive_incident


def test_receive_incident_with_valid_data():
    # Arrange: Prepare input
    state = {
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service is down",
            "description": "Payments are failing",
            "affected_service": "payment-service",
            "occurred_at": "2026-10-24T09:30:00+05:30",
            "status": "pending",
            "severity": "high"
        }
    }

    # Act: Call the function
    result = receive_incident(state)

    # Assert: Check the output
    assert result["incident_id"] == "INC-001"
    assert result["status"] == "received"
    assert result["evidences"] == []
    assert result["errors"] == []

def test_receive_incident_with_missing_id():
    # Arrange: Prepare input
    state = {
        "incident": {
            "title": "Payment service is down",
            "description": "Payments are failing",
            "affected_service": "payment-service",
            "occurred_at": "2026-10-24T09:30:00+05:30",
            "status": "pending",
            "severity": "high"
        }
    }

    # Act: Call the function
    result = receive_incident(state)

    # Assert: Check the output
    
    assert result["status"] == "failed"
    assert result["errors"] == ["Incident ID is missing"]


def test_receive_incident_with_missing_data():
    # Arrange: Prepare input
    state = {
        # "incident": {
        #     "title": "Payment service is down",
        #     "description": "Payments are failing",
        #     "affected_service": "payment-service",
        #     "occurred_at": "2026-10-24T09:30:00+05:30",
        #     "status": "pending",
        #     "severity": "high"
        # }
    }

    # Act: Call the function
    result = receive_incident(state)

    # Assert: Check the output
    
    assert result["status"] == "failed"
    assert result["errors"] == ["Incident data is missing or invalid !"]


# testing 2nd node validate incident
from app.workflow.nodes import receive_incident,validate_incident

# testing with complete data
def test_validate_incident_with_valid_data():
    state = {
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service down",
            "description": "Users cannot make payments",
            "affected_service": "Payment Service",
            "occurred_at": "2026-10-24T10:00:00+05:30",
            "status": "pending",
            "severity": "high"
        },
        "evidences": [],
        "status": "received",
        "errors": []
    }

    result = validate_incident(state)
    print(result)

    assert result["status"] == "validated"
    assert result["errors"] == []
    assert result["incident_id"] == "INC-001"

# testing with invalid data
def test_validate_incident_with_invalid_data():
    state = {
        "incident": {
            "incident_id": "INC-001",
            "title": "",
            "description": "Users cannot make payments",
            "affected_service": "Payment Service",
            "occurred_at": "2026-10-24T10:00:00+05:30",
            "status": "pending",
            "severity": "high"
        },
        "evidences": [],
        "status": "received",
        "errors": []
    }

    result = validate_incident(state)

    assert result["status"] == "failed"
    assert "title is required" in result["errors"]



# testing node 3 prepare incident

from app.workflow.nodes import prepare_investigation

# validate incident
def test_prepare_investigation_with_valid_data():
    state={
        "incident_id": "INC-001", 
        "incident": { 
            "incident_id": "INC-001", 
            "title": "Payment service down", 
            "description": "Users cannot make payments", 
            "affected_service": "Payment Service"
        }, 
        "evidences": [], 
        "status": "validated", 
        "errors": []
    }

    result=prepare_investigation(state)

    assert result["status"]=="prepared"
    assert result["incident_id"]=="INC-001"
    assert result["incident"]==state["incident"]
    assert result["errors"]==[]


# invalid incident
def test_prepare_investigation_with_unvalidated_data():
    state = {
        "incident_id": "INC-001",
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service down",
            "description": "Users cannot make payments",
            "affected_service": "Payment Service"
        },
        "evidences": [],
        "status": "received",
        "errors": []
    }

    result = prepare_investigation(state)

    assert result["status"] != "prepared"


# previous nodes fails
def test_prepare_investigation_with_failed_status():
    state = {
        "incident_id": "INC-001",
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service down"
        },
        "evidences": [],
        "status": "failed",
        "errors": ["Incident validation failed"]
    }

    result = prepare_investigation(state)

    assert result["status"] == "failed"
    assert result["errors"] == ["Incident validation failed"]

# incident id missing
def test_prepare_investigation_with_missing_id():
    state = {
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service down"
        },
        "evidences": [],
        "status": "validated",
        "errors": []
    }

    result = prepare_investigation(state)

    assert result["status"] == "failed"
    assert "incident ID is missing" in result["errors"][0]

# incident data missing
def test_prepare_investigation_with_missing_incident():
    state = {
        "incident_id": "INC-001",
        "evidences": [],
        "status": "validated",
        "errors": []
    }

    result = prepare_investigation(state)

    assert result["status"] == "failed"
    assert "incident data is missing or invalid" in result["errors"][0]

# exisiting evidence are preserved or not
def test_prepare_investigation_preserves_evidences():
    evidence = {
        "source": "logs",
        "content": "Payment service returned HTTP 500"
    }

    state = {
        "incident_id": "INC-001",
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service down"
        },
        "evidences": [evidence],
        "status": "validated",
        "errors": []
    }

    result = prepare_investigation(state)

    assert result["status"] == "prepared"
    assert result["evidences"] == [evidence]


# testing for node 4 mark_ready 
from app.workflow.nodes import mark_ready

# Incident is ready
def test_mark_ready_with_valid_data():
    state = {
        "incident_id": "INC-001",
        "incident": {
            "incident_id": "INC-001",
            "title": "Payment service down",
            "description": "Users cannot make payments",
            "affected_service": "payment-service"
        },
        "evidences": [],
        "status": "prepared",
        "errors": []
    }

    result = mark_ready(state)

    assert result["status"] == "READY"
    assert "completed_at" in result
    assert result["errors"] == []



# Incident is not ready
def test_mark_ready_with_unready_data():
    state = {
        "incident_id": "INC-001",
        "incident": None,
        "evidences": [],
        "status": "received",
        "errors": ["Incident validation failed"]
    }

    result = mark_ready(state)

    assert result["status"] != "ready"