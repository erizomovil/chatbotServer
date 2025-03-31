from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
from pypdf import PdfReader
import os
import re
import json
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

GEMINI_API_KEY = "AIzaSyCtda6E8m4VOQXF0SjoqtH7N1UzKLAcMHs"
genai.configure(api_key=GEMINI_API_KEY)

app = Flask(__name__)
CORS(app, resources={r"/*":{
    "origins":"*",
    "allow_headers": ["Content-Type", "Authorization"],
    "methods": ["GET", "POST", "OPTIONS"] 
}}, supports_credentials=True)
load_dotenv()

conversation_history = {"history": []}
pdfs_text = {}
selected_pdf_for_information = None
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
google_service_account_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
credentials_dict = json.loads(google_service_account_json)
CARPETA_ID = "1S3XB4JQ7JbCZWzje7JG480YbmUvCutQP"

def authenticate_google_drive():
    try:
        creds = service_account.Credentials.from_service_account_info(
            credentials_dict, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error authenticating Google Drive: {e}")
        return None

def read_pdf_from_drive(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        pdf_file = io.BytesIO()
        downloader = MediaIoBaseDownload(pdf_file, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        pdf_file.seek(0)
        
        reader = PdfReader(pdf_file)
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    except Exception as e:
        print(f"Error reading PDF {file_id}: {e}")
        return ""

def load_pdfs_from_drive(service):
    global pdfs_text
    pdfs_text = {}
    
    try:
        results = service.files().list(
            q=f"'{CARPETA_ID}' in parents and mimeType='application/pdf'", 
            fields="files(id, name)").execute()
        files = results.get('files', [])
        
        for file in files:
            print(f"Loading file: {file['name']} ({file['id']})")
            text = read_pdf_from_drive(service, file['id'])
            pdfs_text[file['name']] = text
    except Exception as e:
        print(f"Error loading PDFs from Drive: {e}")

pdfs_associated = {
    'Research Team': 'HandBook.pdf',
    'Networking': 'networking.pdf',
    'Latest News': 'LastestNews.pdf',
    'About the page': 'about_page.pdf',
}

# Load PDFs when the app starts
@app.before_request
def initialize():
    global pdfs_text
    service = authenticate_google_drive()
    if service:
        load_pdfs_from_drive(service)

# Function to check if the question is related to the PDFs
def is_question_related_to_pdfs(question):
    # Define keywords or topics that can help determine if the question
    # is related to the PDFs. This is just an example, you can improve this.
    keywords = ['information', 'details', 'pdf', 'document', 'content', 'chapter', 'section']
    
    # Convert the question to lowercase for comparison
    question = question.lower()
    
    # Search for keyword matches
    for keyword in keywords:
        if re.search(r'\b' + re.escape(keyword) + r'\b', question):
            return True
    return False

# Function to handle basic questions related to PDFs
def handle_basic_pdf_question(question):
    # Try to find a simple answer by searching through the PDFs
    for pdf_name, text in pdfs_text.items():
        if re.search(r'\b' + re.escape(question.lower()) + r'\b', text.lower()):
            # If the question is found in the text, return a portion of the content
            return f"Found this in {pdf_name}: {text[:500]}"  # Limit the text to 500 characters
    return "No relevant information found in the PDFs."

@app.route('/chat', methods=['OPTIONS'])
def handle_options_chat():
    response = jsonify({'message': 'CORS Preflight successful'})
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
    return response

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history, pdfs_text, selected_pdf_for_information

    user_input = request.json['message']
    
    # Agregar el mensaje del usuario al historial de conversación
    conversation_history["history"].append(f"User: {user_input}")

    try:
        if selected_pdf_for_information:
            # Usar el PDF seleccionado previamente para responder la pregunta
            model = genai.GenerativeModel("gemini-1.5-flash")
            gemini_response = model.generate_content(
                f"Answer this question directly based on the content of the PDF only. Do not add additional analysis or explanations.\n\n"
                f"Question: {user_input}\n\n"
                f"Text from the PDF:\n{pdfs_text[selected_pdf_for_information]}"
            ).text.strip()
            
            response = gemini_response
        else:
            # Si no hay un PDF seleccionado, decidir si es una pregunta relacionada con PDFs o no
            if is_question_related_to_pdfs(user_input):
                response = handle_basic_pdf_question(user_input)
            else:
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(f"Question: {user_input}").text.strip()

        # Agregar la respuesta al historial de conversación
        conversation_history['history'].append(f"Response: {response}")
        return jsonify({'response': response})

    except Exception as e:
        print(f"Error processing the request: {e}")
        return jsonify({'error': 'An error occurred on the server'}), 500

@app.route('/app.py/button-action', methods=['GET'])
def handle_get_options_button():
    return 'AYUDA', 200

@app.route('/app.py/button-action', methods=['OPTIONS'])
def handle_options_button():
    response = jsonify({'message': 'CORS Preflight successful'})
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
    return response

@app.route('/button-action', methods=['POST'])
def button_action():
    global selected_pdf_for_information

    data = request.json
    option_selected = data.get('option')

    # Verifica si la opción seleccionada tiene un PDF asociado
    if option_selected in pdfs_associated:
        selected_pdf = pdfs_associated[option_selected]
        if selected_pdf in pdfs_text:
            selected_pdf_for_information = selected_pdf  # Guarda el PDF seleccionado
            response = f"Please ask a specific question related to {option_selected}."
        else:
            response = f"Sorry, the PDF for '{option_selected}' was not found."
    elif option_selected == 'Contacts':
        response = "For more information about contacts, please refer to the corresponding section on the website."
    else:
        response = "Invalid selection."

    return jsonify({'response': response})

if __name__ == '__main__':
    app.run(debug=True)
