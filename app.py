import io
import pandas as pd
import json
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import os
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pprint import pprint
from aiosmtplib import SMTP
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

load_dotenv()

app = FastAPI()

class EmailRequest(BaseModel):
    email: str

class UserID(BaseModel):
    user_id: str

class ExportRequest(BaseModel):
    email: str
    user_id: str


security = HTTPBearer()

# Function to create rows for each symptom
def expand_symptoms(row):
    try:
        symptoms = json.loads(row['symptoms'])
        expanded_rows = []
        for symptom, details in symptoms.items():
            new_row = row.copy()
            new_row['symptom'] = symptom
            if isinstance(details, dict):
                for detail_key, detail_value in details.items():
                    if detail_key == 'Notes':
                        new_row['Symptom Notes'] = detail_value
                    else:
                        new_row[detail_key] = detail_value
            else:
                new_row['details'] = details
            expanded_rows.append(new_row)
        return expanded_rows
    except Exception as e:
        print(f"Error processing row: {e}")
        print(f"Row data: {row}")
        return [row]

# Join the medication names into a single string
def join_medications(medications):
    try:
        meds = json.loads(medications)
        return ', '.join(med['name'] for med in meds)
    except (json.JSONDecodeError, TypeError):
        return medications

def construct_csv(csv_data):
    logs_df = pd.read_csv(io.StringIO(csv_data))
    logs_df = logs_df.drop(columns=['id', 'user_id', 'created_at'])

    # Expand the symptoms into multiple rows
    expanded_rows = logs_df.apply(lambda row: expand_symptoms(row), axis=1).explode().reset_index(drop=True)
    expanded_df = pd.DataFrame(expanded_rows.tolist())

    # Ensure all expected columns exist
    expected_columns = ['title', 'date', 'time', 'symptom', 'Triggers', 'Intensity', 'Frequency', 'Time of Day', 'Symptom Notes', 'medications', 'notes']
    for col in expected_columns:
        if col not in expanded_df.columns:
            expanded_df[col] = None

    # Rearrange columns
    expanded_df = expanded_df[expected_columns]

    # Join the values in the 'Triggers' column with ', '
    expanded_df['Triggers'] = expanded_df['Triggers'].apply(lambda x: ', '.join(x) if isinstance(x, list) else x)
    
    expanded_df['medications'] = expanded_df['medications'].apply(join_medications)

    # Append '/10' to the Intensity column if it exists
    expanded_df['Intensity'] = expanded_df['Intensity'].apply(lambda x: f"{x}/10" if pd.notna(x) else x)

    # Convert the 'time' column to datetime and format it to 'h:mm a'
    expanded_df['time'] = pd.to_datetime(expanded_df['time'], format='%H:%M:%S').dt.strftime('%I:%M %p')

    # Rename columns
    expanded_df.rename(columns={'title': 'Log Title'}, inplace=True)
    expanded_df.rename(columns={'date': 'Date'}, inplace=True)
    expanded_df.rename(columns={'time': 'Time'}, inplace=True)
    expanded_df.rename(columns={'symptom': 'Symptom Logged'}, inplace=True)
    expanded_df.rename(columns={'medications': 'Medications/Treatments'}, inplace=True)
    expanded_df.rename(columns={'notes': 'Log Notes'}, inplace=True)

    return expanded_df

@app.post('/export')
# Old definition for JWT thorugh authorization bearer
# def export(emailReq: EmailRequest, credentials: HTTPAuthorizationCredentials = Depends(security)):
def export(request: ExportRequest):
    user_id = request.user_id

    SENDER_EMAIL='visualsnowlog@gmail.com'
    EMAIL_PASSWORD=os.getenv('EMAIL_PASSWORD')

    # jwt = credentials.credentials
    # print(jwt)
    
    # supabase: Client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_PUBLIC'))
    # Using Supabase service_role key to bypass RLS
    supabase: Client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
    # supabase.auth.get_user(jwt)
    response = supabase.table("logs").select('*').eq('user_id', user_id).csv().execute()
    
    if 'error' in response:
        raise HTTPException(status_code=500, detail=response['error']['message'])
    
    csv_data = response.data
    csvResponse = construct_csv(csv_data)


    return csv_data

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("app:app", host='0.0.0.0', port=8000, reload=True)