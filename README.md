# Azure: File Processing and Archival Workflow

This serverless system automates file upload, backup, and archival using Azure Functions and Blob Storage. The Upload Function validates files (≤50MB, `.jpg`, `.png`, `.pdf`, `.docx`), stores them securely, and logs metadata in Application Insights. The Backup & Archival Function creates redundant copies and archives expired files using gzip compression. ThreadPoolExecutor enables parallel processing for efficiency, while Azure Key Vault secures credentials. Built with an event-driven architecture, the system ensures scalability, automation, and maintainability for dynamic workloads.

## Prerequisites

- An Azure subscription.
- Azure CLI or access to the Azure Portal.
- Python environment to run the test script.
- Git installed on your local machine.

## Steps to Set Up

1. **Clone the Repository**
   - First, clone the repository to your local machine:
     ```sh
     git clone <repository_url>
     cd <repository_folder>
     ```

2. **Set Up an Azure Function App**
   - Create a **Function App** on the Azure Portal (Make sure to enable Application Insights for the Function App).
   - Enable **Managed Identity** for the Function App.
   - Assign the **Key Vault Secrets User** role to the Function App in the Key Vault.
   - Set up an **App Setting** in the Function App called **ApplicationInsightsConnectionString**, which is the connection string for Azure Application Insights.

3. **Create Azure Blob Storage Containers**
   - Create an **Azure Blob Storage** account with the following containers:
     - **upload-cont**: For initial file uploads.
     - **backup-cont**: For backup copies of uploaded files.
     - **archive-cont**: For archiving older files.
   - Add the **storage key** as a secret in the Key Vault (under the name **AzureStorageConnectionString**).

4. **Create an Azure Key Vault**
   - Set up an **Azure Key Vault** and create the following secrets:
     - **ApplicationInsightsConnectionString**: The connection string for Azure Application Insights.
     - **AzureStorageConnectionString**: The connection string for Azure Blob Storage.

5. **Set Up local.settings.json**
   - Insert the relevant values into these variables:
     - **AzureWebJobsStorage**: The connection string for Azure Blob Storage.
     - **AZURE_KEY_VAULT_URL**: The URL for your Key Vault.

6. **Deploy the Azure Function**
   - Deploy the cloned code to your Function App:
     - You can use Azure CLI or the Azure Portal to deploy the code.
     - Ensure the Function App's app settings are correctly configured to access Key Vault secrets.

7. **Run the Workflow**
   - To trigger the **first function** (file upload), run `test.py`:
     - Update the **Function App URL** in `test.py` to match your own Function App.
     - Replace the **local file path** in `test.py` with the path to the file you want to upload.
   - Run the script using Python:
     ```sh
     python test.py
     ```

Feel free to reach out if you have any questions or encounter issues during the setup. Happy coding!

