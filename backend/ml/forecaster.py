import json
import os

PREDICTIONS_PATH = os.path.join(os.path.dirname(__file__), "../models/predictions.json")


def get_next_24hr_forecast() -> dict:
    """Saved Prophet predictions for Germany (static file, see roadmap for live retraining)."""
    try:
        with open(PREDICTIONS_PATH, "r") as f:
            predictions = json.load(f)
    except (OSError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}

    return {
        "status": "success",
        "country": "Germany",
        "model": "Prophet",
        "total_predictions": len(predictions),
        "predictions": predictions,
    }
