import azure.functions as func
import logging
import random
from datetime import datetime
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from typing import Optional
import pyodbc
import json
import time
from azure.functions.decorators.core import DataType

app = func.FunctionApp()

def get_db_connection_string() -> Optional[str]:
    try:
        credential = DefaultAzureCredential()
        key_vault_url = "https://kv3211.vault.azure.net/"
        client = SecretClient(vault_url=key_vault_url, credential=credential)
        return client.get_secret("SQLConnectionString").value
    except Exception as e:
        logging.error(f"Error getting connection string: {str(e)}")
        return None

def initialize_table(conn: pyodbc.Connection):
    try:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SensorData')
            CREATE TABLE SensorData (
                ID INT IDENTITY(1,1) PRIMARY KEY,
                Temperature FLOAT,
                Humidity FLOAT,
                Timestamp DATETIME
            )
        """)
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Error initializing table: {str(e)}")
        return False

@app.route(route="sensor_trigger")
def sensor_trigger(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Generate random sensor data
        temperature = round(random.uniform(20.0, 30.0), 2)
        humidity = round(random.uniform(30.0, 70.0), 2)
        current_time = datetime.utcnow()

        # Get database connection
        conn_string = get_db_connection_string()
        if not conn_string:
            return func.HttpResponse(
                "Failed to get database connection string from Key Vault",
                status_code=500
            )

        # Connect to database
        with pyodbc.connect(conn_string) as conn:
            # Initialize table if it doesn't exist
            if not initialize_table(conn):
                return func.HttpResponse(
                    "Failed to initialize database table",
                    status_code=500
                )

            # Insert sensor data
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO SensorData (Temperature, Humidity, Timestamp) VALUES (?, ?, ?)",
                temperature, humidity, current_time
            )
            conn.commit()

        return func.HttpResponse(
            f"Successfully recorded sensor data: Temperature={temperature}°C, Humidity={humidity}%",
            status_code=200
        )

    except Exception as e:
        logging.error(str(e))
        return func.HttpResponse(
            f"Error processing sensor data: {str(e)}",
            status_code=500
        )

@app.function_name(name="ProcessSensorData")
@app.sql_trigger(arg_name="sensor_data",
                 table_name="SensorData",
                 connection_string_setting="SqlConnectionString")
def process_sensor_data(sensor_data: str) -> None:
    try:
        # Log incoming changes
        logging.info("Processing sensor data changes: %s", json.loads(sensor_data))
        
        # Get database connection from settings
        conn_str = app.settings["SqlConnectionString"]
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        # Create statistics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS SensorStatistics (
                ID INT IDENTITY(1,1) PRIMARY KEY,
                Timestamp DATETIME,
                MaxTemp FLOAT,
                MinTemp FLOAT,
                AvgTemp FLOAT,
                MaxHumidity FLOAT,
                MinHumidity FLOAT,
                AvgHumidity FLOAT,
                ExecutionTime FLOAT
            )
        """)

        # Calculate statistics
        cursor.execute("""
            SELECT 
                MAX(Temperature) as MaxTemp,
                MIN(Temperature) as MinTemp,
                AVG(Temperature) as AvgTemp,
                MAX(Humidity) as MaxHumidity,
                MIN(Humidity) as MinHumidity,
                AVG(Humidity) as AvgHumidity
            FROM SensorData
        """)

        # Store results
        stats = cursor.fetchone()
        execution_time = datetime.now()
        
        cursor.execute("""
            INSERT INTO SensorStatistics 
            (Timestamp, MaxTemp, MinTemp, AvgTemp, MaxHumidity, MinHumidity, AvgHumidity, ExecutionTime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (execution_time, *stats))
        
        conn.commit()
        logging.info("Statistics calculated and stored successfully")

    except Exception as e:
        logging.error(f"Error processing sensor data: {str(e)}")
        raise