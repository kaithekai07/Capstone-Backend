from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return 'Safesight AI Backend is Running'

@app.route('/analyze', methods=['POST'])
def analyze():
    file = request.files.get('file')
    if not file:
        return jsonify({"result": "No file received"}), 400

    car_id = request.form.get('carId')
    date = request.form.get('date')
    desc = request.form.get('description')

    result = f"CAR {car_id} submitted on {date}.\nDescription: {desc}\nFilename: {file.filename}"
    return jsonify({"result": result})

if __name__ == '__main__':
    app.run()
