# Birdies Sales Analytics API Documentation

## Overview

The Sales Analytics API provides endpoints for collecting daily POS sales data and querying aggregated sales information. All endpoints use JSON for request and response payloads.

**Base URL:** `https://loyalty.birdiesstore.com/api/sales`

---

## Authentication

Currently, the API does not require authentication. However, it is recommended to implement API key authentication in production for security.

---

## Data Ingestion Endpoints

### Upload Raw XML

**Endpoint:** `POST /raw-xml/upload`

**Purpose:** Upload raw XML files from POS for audit trail and backup.

**Request Body:**
```json
{
  "pdiStoreNumber": "1200",
  "reportType": "CPJR",
  "businessDate": "2025-02-08",
  "fileName": "CPJR08022025235955.xml",
  "xmlContent": "<XML content as string>"
}
```

**Required Fields:**
- `pdiStoreNumber` (string): PDI store number (e.g., "1200")
- `reportType` (string): Type of report - "CPJR", "FGM", "MCM", or "ISM"
- `businessDate` (string): Business date in YYYY-MM-DD format
- `fileName` (string): Original filename
- `xmlContent` (string): Full XML content

**Response:**
```json
{
  "success": true,
  "id": 123,
  "message": "Raw XML stored successfully"
}
```

**Status Codes:**
- `201` - Created successfully
- `400` - Missing required fields
- `500` - Server error

---

### Batch Upload Transactions

**Endpoint:** `POST /transactions/batch`

**Purpose:** Upload daily transactions in batch.

**Request Body:**
```json
{
  "transactions": [
    {
      "pdiStoreNumber": "1200",
      "businessDate": "2025-02-08",
      "transactionId": "TX123456",
      "transactionDateTime": "2025-02-08T14:30:00",
      "cashierId": "CASHIER01",
      "fuelVolume": 12.5,
      "fuelAmount": 45.00,
      "merchAmount": 15.50,
      "totalAmount": 60.50,
      "tenderType": "CREDIT"
    }
  ]
}
```

**Transaction Fields:**
- `pdiStoreNumber` (string, required): Store identifier
- `businessDate` (string, required): Date in YYYY-MM-DD format
- `transactionId` (string, required): Unique transaction ID
- `transactionDateTime` (ISO 8601 string, required): Transaction timestamp
- `cashierId` (string, optional): Cashier ID
- `fuelVolume` (number, optional): Gallons of fuel
- `fuelAmount` (number, optional): Dollar amount of fuel
- `merchAmount` (number, optional): Dollar amount of merchandise
- `totalAmount` (number, required): Total transaction amount
- `tenderType` (string, optional): Payment method (CASH, CREDIT, DEBIT, etc.)

**Response:**
```json
{
  "success": true,
  "count": 345,
  "message": "Transactions inserted successfully"
}
```

---

### Batch Upload Fuel Grades

**Endpoint:** `POST /fuel-grades/batch`

**Purpose:** Upload daily fuel sales by grade.

**Request Body:**
```json
{
  "fuelGrades": [
    {
      "pdiStoreNumber": "1200",
      "businessDate": "2025-02-08",
      "gradeId": "001",
      "gradeName": "Regular Unleaded",
      "volume": 1234.567,
      "amount": 4567.89,
      "discountAmount": 0.00
    }
  ]
}
```

**Fuel Grade Fields:**
- `pdiStoreNumber` (string, required): Store identifier
- `businessDate` (string, required): Date in YYYY-MM-DD format
- `gradeId` (string, required): Fuel grade ID
- `gradeName` (string, optional): Fuel grade name
- `volume` (number, required): Gallons sold
- `amount` (number, required): Dollar amount
- `discountAmount` (number, optional): Total discounts

**Response:**
```json
{
  "success": true,
  "count": 3,
  "message": "Fuel grades inserted successfully"
}
```

---

### Batch Upload Items

**Endpoint:** `POST /items/batch`

**Purpose:** Upload individual item sales (UPC-level detail).

**Request Body:**
```json
{
  "items": [
    {
      "pdiStoreNumber": "1200",
      "businessDate": "2025-02-08",
      "upc": "012000001234",
      "description": "Coca-Cola 20oz",
      "quantity": 45,
      "salesAmount": 89.55
    }
  ]
}
```

**Item Fields:**
- `pdiStoreNumber` (string, required): Store identifier
- `businessDate` (string, required): Date in YYYY-MM-DD format
- `upc` (string, required): UPC/barcode
- `description` (string, optional): Item description
- `quantity` (number, required): Units sold
- `salesAmount` (number, required): Total sales amount

---

### Batch Upload Departments

**Endpoint:** `POST /departments/batch`

**Purpose:** Upload department-level sales rollups.

**Request Body:**
```json
{
  "departments": [
    {
      "pdiStoreNumber": "1200",
      "businessDate": "2025-02-08",
      "departmentCode": "TOBACCO",
      "departmentName": "Tobacco Products",
      "salesAmount": 456.78,
      "quantity": 89,
      "transactionCount": 45
    }
  ]
}
```

**Department Fields:**
- `pdiStoreNumber` (string, required): Store identifier
- `businessDate` (string, required): Date in YYYY-MM-DD format
- `departmentCode` (string, required): Department code
- `departmentName` (string, optional): Department name
- `salesAmount` (number, required): Total sales
- `quantity` (number, required): Units sold
- `transactionCount` (number, required): Number of transactions

---

## Data Query Endpoints

All query endpoints support filtering via query parameters.

### Get Transactions

**Endpoint:** `GET /transactions`

**Query Parameters:**
- `pdiStoreNumber` (optional): Filter by store
- `businessDate` (optional): Filter by specific date (YYYY-MM-DD)
- `startDate` (optional): Filter by date range start
- `endDate` (optional): Filter by date range end
- `limit` (optional): Maximum number of records to return
- `offset` (optional): Pagination offset

**Example Request:**
```
GET /transactions?pdiStoreNumber=1200&businessDate=2025-02-08&limit=100
```

**Response:**
```json
[
  {
    "id": 1,
    "locationId": 5,
    "pdiStoreNumber": "1200",
    "businessDate": "2025-02-08",
    "transactionId": "TX123456",
    "transactionDateTime": "2025-02-08T14:30:00.000Z",
    "cashierId": "CASHIER01",
    "fuelVolume": "12.500",
    "fuelAmount": "45.00",
    "merchAmount": "15.50",
    "totalAmount": "60.50",
    "tenderType": "CREDIT",
    "createdAt": "2025-02-09T01:00:00.000Z"
  }
]
```

---

### Get Fuel Grades

**Endpoint:** `GET /fuel-grades`

**Query Parameters:**
- `pdiStoreNumber` (optional): Filter by store
- `businessDate` (optional): Filter by specific date
- `startDate` (optional): Date range start
- `endDate` (optional): Date range end

**Example Request:**
```
GET /fuel-grades?pdiStoreNumber=1200&businessDate=2025-02-08
```

**Response:**
```json
[
  {
    "id": 1,
    "locationId": 5,
    "pdiStoreNumber": "1200",
    "businessDate": "2025-02-08",
    "gradeId": "001",
    "gradeName": "Regular Unleaded",
    "volume": "1234.567",
    "amount": "4567.89",
    "discountAmount": "0.00",
    "createdAt": "2025-02-09T01:00:00.000Z"
  }
]
```

---

### Get Items

**Endpoint:** `GET /items`

**Query Parameters:**
- `pdiStoreNumber` (optional): Filter by store
- `businessDate` (optional): Filter by specific date
- `startDate` (optional): Date range start
- `endDate` (optional): Date range end
- `limit` (optional): Maximum number of records

**Example Request:**
```
GET /items?pdiStoreNumber=1200&startDate=2025-02-01&endDate=2025-02-08&limit=50
```

**Response:**
```json
[
  {
    "id": 1,
    "locationId": 5,
    "pdiStoreNumber": "1200",
    "businessDate": "2025-02-08",
    "upc": "012000001234",
    "description": "Coca-Cola 20oz",
    "quantity": "45.000",
    "salesAmount": "89.55",
    "createdAt": "2025-02-09T01:00:00.000Z"
  }
]
```

---

### Get Departments

**Endpoint:** `GET /departments`

**Query Parameters:**
- `pdiStoreNumber` (optional): Filter by store
- `businessDate` (optional): Filter by specific date
- `startDate` (optional): Date range start
- `endDate` (optional): Date range end

**Response:**
```json
[
  {
    "id": 1,
    "locationId": 5,
    "pdiStoreNumber": "1200",
    "businessDate": "2025-02-08",
    "departmentCode": "TOBACCO",
    "departmentName": "Tobacco Products",
    "salesAmount": "456.78",
    "quantity": "89.000",
    "transactionCount": 45,
    "createdAt": "2025-02-09T01:00:00.000Z"
  }
]
```

---

### Get Sales Summary

**Endpoint:** `GET /summary`

**Purpose:** Get aggregated sales summary for a date range.

**Query Parameters:**
- `pdiStoreNumber` (optional): Filter by store
- `businessDate` (optional): Filter by specific date
- `startDate` (optional): Date range start
- `endDate` (optional): Date range end

**Example Request:**
```
GET /summary?pdiStoreNumber=1200&businessDate=2025-02-08
```

**Response:**
```json
{
  "totalTransactions": 345,
  "totalSales": "12567.89",
  "totalFuelSales": "8567.89",
  "totalMerchSales": "4000.00",
  "totalFuelVolume": "2345.678"
}
```

---

### Get Raw XML Files

**Endpoint:** `GET /raw-xml`

**Purpose:** Retrieve uploaded raw XML files for audit or reprocessing.

**Query Parameters:**
- `pdiStoreNumber` (optional): Filter by store
- `reportType` (optional): Filter by report type
- `businessDate` (optional): Filter by specific date
- `startDate` (optional): Date range start
- `endDate` (optional): Date range end

**Response:**
```json
[
  {
    "id": 1,
    "locationId": 5,
    "pdiStoreNumber": "1200",
    "reportType": "CPJR",
    "businessDate": "2025-02-08",
    "fileName": "CPJR08022025235955.xml",
    "xmlContent": "<XML content>",
    "fileSize": 1234567,
    "uploadedAt": "2025-02-09T01:00:00.000Z",
    "processedAt": null,
    "processingStatus": "pending",
    "errorMessage": null
  }
]
```

---

## Error Handling

All endpoints return standard HTTP status codes:

- `200` - Success
- `201` - Created
- `400` - Bad Request (missing or invalid parameters)
- `404` - Not Found
- `500` - Internal Server Error

Error responses include a descriptive message:

```json
{
  "error": "Missing required fields: pdiStoreNumber, reportType"
}
```

---

## Rate Limiting

Currently, no rate limiting is implemented. Consider adding rate limiting in production to prevent abuse.

---

## Best Practices

### Batch Uploads
- Use batch endpoints for better performance
- Recommended batch size: 100-1000 records per request
- Upload raw XML files first for audit trail

### Error Recovery
- Implement retry logic with exponential backoff
- Store failed uploads locally and retry later
- Log all API responses for troubleshooting

### Data Integrity
- Always include `pdiStoreNumber` to link data to stores
- Use consistent date format (YYYY-MM-DD)
- Validate data before sending to API

---

## Example Integration

### Python Example (from Store Deployment Package)

```python
import requests

API_BASE_URL = "https://loyalty.birdiesstore.com/api/sales"

def upload_transactions(transactions):
    url = f"{API_BASE_URL}/transactions/batch"
    payload = {"transactions": transactions}
    
    response = requests.post(url, json=payload, timeout=60)
    
    if response.status_code == 201:
        print("Upload successful!")
        return True
    else:
        print(f"Upload failed: {response.text}")
        return False

# Usage
transactions = [
    {
        "pdiStoreNumber": "1200",
        "businessDate": "2025-02-08",
        "transactionId": "TX123",
        "transactionDateTime": "2025-02-08T14:30:00",
        "totalAmount": 60.50
    }
]

upload_transactions(transactions)
```

---

## Changelog

**v1.0 (November 2025)**
- Initial release
- Raw XML upload endpoint
- Batch data ingestion endpoints
- Query endpoints with filtering
- Sales summary aggregation
