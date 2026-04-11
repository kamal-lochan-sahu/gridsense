import pickle
import json
import os
from datetime import datetime

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../models/prophet_model.pkl")
PREDICTIONS_PATH = os.path.join(os.path.dirname(__file__), "../models/predictions.json")


def load_predictions():
    """
    Saved predictions.json se data load karo
    """
    try:
        with open(PREDICTIONS_PATH, "r") as f:
            predictions = json.load(f)
        return {
            "status": "success",
            "country": "Germany",
            "model": "Prophet",
            "total_predictions": len(predictions),
            "predictions": predictions
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def get_next_24hr_forecast():
    """
    Next 24hr ka forecast return karo
    """
    data = load_predictions()
    if data["status"] == "success":
        return data
    return data


if __name__ == "__main__":
    result = get_next_24hr_forecast()
    print(f"Status: {result['status']}")
    print(f"Total predictions: {result['total_predictions']}")
    print(f"First prediction: {result['predictions'][0]}")