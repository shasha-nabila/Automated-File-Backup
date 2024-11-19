import azure.functions as func
from opencensus.ext.azure.log_exporter import AzureLogHandler
import logging
import os
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
import mimetypes
from azure.keyvault.secrets import SecretClient
import datetime
import io
import time
import gzip
from datetime import datetime, timezone

def get_secrets_from_keyvault():
    vault_url = os.environ["AZURE_KEY_VAULT_URL"]
    
    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        
        # Get both secrets
        storage_connection_string = client.get_secret("AzureStorageConnectionString").value
        app_insights_connection_string = client.get_secret("ApplicationInsightsConnectionString").value
        
        return storage_connection_string, app_insights_connection_string
    except Exception as e:
        logging.error(f"Error retrieving secrets from Key Vault: {str(e)}")
        raise

# Setup logging with Application Insights
storage_conn_str, app_insights_conn_str = get_secrets_from_keyvault()
logger = logging.getLogger(__name__)
logger.addHandler(AzureLogHandler(connection_string=app_insights_conn_str))

logging.getLogger().setLevel(logging.INFO)

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

def init_blob_service():
    storage_conn_str, _ = get_secrets_from_keyvault()
    return BlobServiceClient.from_connection_string(storage_conn_str)

def validate_file(file):
    # Add your validation rules
    max_size = 10 * 1024 * 1024  # 10MB
    allowed_types = ['.jpg', '.png', '.pdf', '.docx']
    
    if file.content_length > max_size:
        return False, "File too large"
    
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_types:
        return False, "File type not allowed"
        
    return True, ""

@app.route(route="upload", methods=["POST"])
async def upload(req: func.HttpRequest) -> func.HttpResponse:
    try:
        file = req.files.get('file')
        if not file:
            return func.HttpResponse("No file uploaded", status_code=400)
            
        # Validate file
        is_valid, error = validate_file(file)
        if not is_valid:
            logger.warning(f"Invalid file upload attempt: {error}")
            return func.HttpResponse(f"Invalid file: {error}", status_code=400)
            
        filename = file.filename
        file_data = file.read()
        
        # Get storage connection string
        storage_conn_str, _ = get_secrets_from_keyvault()
        
        # Upload to blob storage
        blob_service_client = BlobServiceClient.from_connection_string(storage_conn_str)
        container_client = blob_service_client.get_container_client("upload-cont")
        blob_client = container_client.get_blob_client(filename)
        blob_client.upload_blob(file_data, overwrite=True)
        
        # Log metadata to Application Insights
        metadata = {
            'filename': filename,
            'size_bytes': len(file_data),
            'content_type': mimetypes.guess_type(filename)[0],
            'upload_timestamp': datetime.now(timezone.utc).isoformat()
        }
        logger.info('File upload successful', extra={'custom_dimensions': metadata})
        
        return func.HttpResponse(f"File uploaded successfully: {filename}", status_code=200)
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        return func.HttpResponse(f"Upload failed: {str(e)}", status_code=500)

@app.blob_trigger(arg_name="myblob", 
                 path="upload-cont/{name}",
                 connection="AzureWebJobsStorage")
async def process_backup(myblob: func.InputStream):
    try:
        start_time = time.time()
        
        # Get container names from settings
        backup_container = os.environ["BACKUP_CONTAINER_NAME"]
        archive_container = os.environ["ARCHIVE_CONTAINER_NAME"]
        retention_days = int(os.environ["RETENTION_DAYS"])
        
        # Initialize blob service
        blob_service_client = init_blob_service()
        
        # Create backup copy
        source_blob_name = myblob.name.split('/')[-1]
        backup_blob_client = blob_service_client.get_container_client(backup_container).get_blob_client(source_blob_name)
        backup_blob_client.upload_blob(myblob.read(), overwrite=True)
        
        # Check file age and archive if needed
        blob_properties = backup_blob_client.get_blob_properties()
        current_time = datetime.now(timezone.utc)
        file_age = (current_time - blob_properties.last_modified).days
        
        if file_age > retention_days:
            # Compress file
            compressed_data = io.BytesIO()
            with gzip.GzipFile(fileobj=compressed_data, mode='wb') as gz:
                gz.write(myblob.read())
            compressed_data.seek(0)
            
            archive_blob_client = blob_service_client.get_container_client(archive_container).get_blob_client(f"{source_blob_name}.gz")
            archive_blob_client.upload_blob(compressed_data, overwrite=True)
            
            # Delete from backup container
            backup_blob_client.delete_blob()
        
        # Log processing details
        execution_time = time.time() - start_time
        metadata = {
            'filename': source_blob_name,
            'backup_container': backup_container,
            'was_archived': file_age > retention_days,
            'processing_time': execution_time,
            'file_age_days': file_age
        }
        logger.info('Backup processing completed', extra={'custom_dimensions': metadata})
        
    except Exception as e:
        logger.error(f"Backup processing failed: {str(e)}")
        raise
