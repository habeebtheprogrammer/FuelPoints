// Test Passport parser to ensure it still works
import fs from 'fs';

const BACKEND_URL = 'http://localhost:3001';

const PASSPORT_FILES = [
  {
    file: 'attached_assets/FGM34025111423560113476255.xml',
    reportType: 'FGM',
    businessDate: '2025-11-14'
  }
];

const PDI_STORE_NUMBER = '1200';  // Passport store

async function uploadFile(fileInfo) {
  try {
    const xmlContent = fs.readFileSync(fileInfo.file, 'utf8');
    const fileName = fileInfo.file.split('/').pop();
    
    console.log(`📤 Uploading ${fileName}...`);
    
    const response = await fetch(`${BACKEND_URL}/api/sales/raw-xml/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pdiStoreNumber: PDI_STORE_NUMBER,
        reportType: fileInfo.reportType,
        businessDate: fileInfo.businessDate,
        fileName: fileName,
        xmlContent: xmlContent
      })
    });
    
    const result = await response.json();
    
    if (response.ok) {
      console.log(`✅ Uploaded ${fileName} - ID: ${result.id}`);
      return result.id;
    } else {
      console.log(`❌ Failed to upload ${fileName}: ${result.error}`);
    }
  } catch (error) {
    console.error(`❌ Error uploading ${fileInfo.file}:`, error.message);
  }
}

async function testParsing(businessDate) {
  console.log(`\n📊 Testing Passport parser for ${businessDate}...`);
  
  const response = await fetch(`${BACKEND_URL}/api/sales/process-xml`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ businessDate })
  });
  
  const result = await response.json();
  console.log('Parse result:', JSON.stringify(result, null, 2));
}

async function main() {
  console.log('============================================================');
  console.log('🧪 Testing Passport Parser (Gilbarco)');
  console.log('============================================================');
  console.log(`Store: ${PDI_STORE_NUMBER} (Mechanicsville - Passport)`);
  console.log('============================================================\n');
  
  for (const fileInfo of PASSPORT_FILES) {
    await uploadFile(fileInfo);
  }
  
  await testParsing('2025-11-14');
  
  console.log('\n✅ Passport parser test complete!');
}

main().catch(console.error);
