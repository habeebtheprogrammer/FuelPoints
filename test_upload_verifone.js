// Test script to upload Verifone XML files to development server
import fs from 'fs';
import path from 'path';

const BACKEND_URL = process.env.REPL_SLUG 
  ? 'http://localhost:3001'  // Development (local)
  : 'https://salmanloyalty.replit.app';  // Production

const TEST_FILES = [
  {
    file: 'attached_assets/passport_files/04/vposjournal_prevClose_SEQ312_20250204_235906.xml',
    reportType: 'CPJR',
    businessDate: '2025-02-04'
  },
  {
    file: 'attached_assets/passport_files/04/vfueltotals_previousClose_SEQ312_20250204_235906.xml',
    reportType: 'FGM',
    businessDate: '2025-02-04'
  },
  {
    file: 'attached_assets/passport_files/04/vrubyrept_category_prevClose_SEQ312_20250204_235906.xml',
    reportType: 'MCM',
    businessDate: '2025-02-04'
  },
  {
    file: 'attached_assets/passport_files/04/vrubyrept_allProd_prevClose_SEQ312_20250204_235906.xml',
    reportType: 'ISM',
    businessDate: '2025-02-04'
  }
];

const PDI_STORE_NUMBER = '1330';  // Hollywood test store

async function uploadFile(fileInfo) {
  try {
    const xmlContent = fs.readFileSync(fileInfo.file, 'utf8');
    const fileName = path.basename(fileInfo.file);
    
    console.log(`📤 Uploading ${fileName}...`);
    
    const response = await fetch(`${BACKEND_URL}/api/sales/raw-xml/upload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
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
    } else {
      console.log(`❌ Failed to upload ${fileName}: ${result.error || response.statusText}`);
    }
    
    return result;
  } catch (error) {
    console.log(`❌ Error uploading ${fileInfo.file}:`, error.message);
  }
}

async function main() {
  console.log('============================================================');
  console.log('🧪 Testing Verifone XML Parser');
  console.log('============================================================');
  console.log(`Store: ${PDI_STORE_NUMBER}`);
  console.log(`Backend: ${BACKEND_URL}`);
  console.log(`Files: ${TEST_FILES.length}`);
  console.log('============================================================\n');
  
  for (const fileInfo of TEST_FILES) {
    await uploadFile(fileInfo);
    await new Promise(resolve => setTimeout(resolve, 100)); // Small delay
  }
  
  console.log('\n============================================================');
  console.log('✨ Upload complete! Files are pending parsing.');
  console.log('============================================================');
  console.log('Next: Background job will parse in ~30 minutes');
  console.log('Or manually trigger parsing by checking Sales Analytics');
  console.log('============================================================');
}

main().catch(console.log);
