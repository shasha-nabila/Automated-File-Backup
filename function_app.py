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
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def process_single_file(blob_service_client, file_name, upload_container, backup_container, archive_container):
    try:
        # Copy to backup container
        source_blob = blob_service_client.get_blob_client(
            container=upload_container,
            blob=file_name
        )
        
        backup_blob = blob_service_client.get_blob_client(
            container=backup_container,
            blob=file_name
        )
        
        backup_blob.start_copy_from_url(source_blob.url)
        
        # Check retention period and archive if needed
        blob_properties = source_blob.get_blob_properties()
        creation_time = blob_properties.creation_time
        retention_days = int(os.environ["RETENTION_DAYS"])
        
        if datetime.now(timezone.utc) - creation_time > timedelta(days=retention_days):
            # Download blob content
            download_stream = source_blob.download_blob()
            
            # Compress content
            compressed_content = gzip.compress(download_stream.readall())
            
            # Upload to archive container
            archive_blob = blob_service_client.get_blob_client(
                container=archive_container,
                blob=f"{file_name}.gz"
            )
            archive_blob.upload_blob(compressed_content, overwrite=True)
            
            # Delete original blob
            source_blob.delete_blob()
            
        logger.info(f"Successfully processed file: {file_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing file {file_name}: {str(e)}")
        return False

@app.blob_trigger(arg_name="myblob", 
                 path="upload-cont/{name}",
                 connection="AzureWebJobsStorage")
def backup_function(myblob: func.InputStream):
    start_time = time.time()
    
    blob_service_client = init_blob_service()
    upload_container = os.environ["UPLOAD_CONTAINER_NAME"]
    backup_container = os.environ["BACKUP_CONTAINER_NAME"]
    archive_container = os.environ["ARCHIVE_CONTAINER_NAME"]
    
    # Get list of files to process
    container_client = blob_service_client.get_container_client(upload_container)
    blobs = container_client.list_blobs()
    
    # Process files in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_file = {
            executor.submit(
                process_single_file,
                blob_service_client,
                blob.name,
                upload_container,
                backup_container,
                archive_container
            ): blob.name for blob in blobs
        }
        
        for future in as_completed(future_to_file):
            file_name = future_to_file[future]
            try:
                success = future.result()
                if success:
                    logger.info(f"Completed processing file: {file_name}")
                else:
                    logger.error(f"Failed to process file: {file_name}")
            except Exception as e:
                logger.error(f"Exception processing file {file_name}: {str(e)}")
    
    end_time = time.time()
    logger.info(f"Backup function completed. Total processing time: {end_time - start_time} seconds")
