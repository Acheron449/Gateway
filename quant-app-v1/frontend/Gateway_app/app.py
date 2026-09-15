from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "static" / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

@app.route("/")
def home():

    pricing_tiers = [
        {"name": "Free", "price": "$0", "credits": "800 credits", "featured": False, "cta": "Get Started Free"},
        {"name": "Starter", "price": "$9", "credits": "2,000 credits/mo", "featured": False, "cta": "Select Plan"},
        {"name": "Pro", "price": "$29", "credits": "4,000 credits/mo", "featured": True, "cta": "Start Pro Trial"},
        {"name": "Elite", "price": "$79", "credits": "8,000 credits/mo", "featured": False, "cta": "Select Plan"}
    ]
    return render_template("index.html", tiers=pricing_tiers)

@app.route("/api/generate", methods=["POST"])
def generate_logic():

    data = request.get_json()
    prompt_text = data.get("prompt", "")
    

    return jsonify({
        "status": "completed",
        "metrics": {
            "win_rate": "68.4%",
            "drawdown": "-3.8%",
            "trades": "126",
            "profit_factor": "2.34"
        }
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
