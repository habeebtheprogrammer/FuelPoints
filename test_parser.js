// Manual test of XML parser
import storage from './server/storage.js';
import { parseCPJR, parseFGM, parseMCM, parseISM } from './server/xmlParsers.js';

async function testParser() {
  console.log('============================================================');
  console.log('🧪 Testing Verifone XML Parser');
  console.log('============================================================\n');
  
  // Get pending files for store 1330
  const pendingFiles = await storage.getRawXmlByFilters({
    pdiStoreNumber: '1330',
  });
  
  console.log(`Found ${pendingFiles.length} files for store 1330\n`);
  
  for (const file of pendingFiles) {
    if (file.processingStatus !== 'pending') {
      console.log(`⏭️  Skipping ${file.fileName} (already ${file.processingStatus})`);
      continue;
    }
    
    try {
      console.log(`📄 Processing ${file.fileName} (${file.reportType})...`);
      
      if (file.reportType === 'CPJR') {
        const transactions = await parseCPJR(file.xmlContent, file.businessDate);
        console.log(`  ✅ Parsed ${transactions.length} transactions`);
        
        // Store transactions
        for (const txn of transactions) {
          await storage.createSalesTransaction({
            locationId: file.locationId,
            pdiStoreNumber: file.pdiStoreNumber,
            businessDate: file.businessDate,
            transactionId: txn.transactionId,
            sequenceNumber: txn.sequenceNumber,
            timestamp: txn.timestamp,
            totalAmount: txn.totalAmount,
            fuelAmount: txn.fuelAmount,
            merchandiseAmount: txn.merchandiseAmount,
            tenderType: txn.tenderType,
          });
        }
        console.log(`  💾 Stored ${transactions.length} transactions\n`);
        
      } else if (file.reportType === 'FGM') {
        const fuelGrades = await parseFGM(file.xmlContent, file.businessDate);
        console.log(`  ✅ Parsed ${fuelGrades.length} fuel grades`);
        
        // Store fuel grades
        for (const grade of fuelGrades) {
          await storage.createSalesFuelGrade({
            locationId: file.locationId,
            pdiStoreNumber: file.pdiStoreNumber,
            businessDate: file.businessDate,
            gradeId: grade.gradeId,
            gradeName: grade.gradeName,
            volume: grade.volume,
            amount: grade.amount,
            discountAmount: grade.discountAmount,
          });
        }
        console.log(`  💾 Stored ${fuelGrades.length} fuel grades\n`);
        
      } else if (file.reportType === 'MCM') {
        const departments = await parseMCM(file.xmlContent, file.businessDate);
        console.log(`  ✅ Parsed ${departments.length} departments`);
        
        // Store departments
        for (const dept of departments) {
          await storage.createSalesDepartment({
            locationId: file.locationId,
            pdiStoreNumber: file.pdiStoreNumber,
            businessDate: file.businessDate,
            departmentCode: dept.departmentCode,
            departmentName: dept.departmentName,
            salesAmount: dept.salesAmount,
            quantity: dept.quantity,
            transactionCount: dept.transactionCount,
          });
        }
        console.log(`  💾 Stored ${departments.length} departments\n`);
        
      } else if (file.reportType === 'ISM') {
        const items = await parseISM(file.xmlContent, file.businessDate);
        console.log(`  ✅ Parsed ${items.length} items`);
        
        // Store items
        for (const item of items) {
          await storage.createSalesItem({
            locationId: file.locationId,
            pdiStoreNumber: file.pdiStoreNumber,
            businessDate: file.businessDate,
            upc: item.upc,
            description: item.description,
            quantity: item.quantity,
            salesAmount: item.salesAmount,
          });
        }
        console.log(`  💾 Stored ${items.length} items\n`);
      }
      
      // Mark as processed
      await storage.updateRawXmlStatus(file.id, 'processed', null);
      console.log(`  ✅ Marked ${file.fileName} as processed\n`);
      
    } catch (error) {
      console.error(`  ❌ Error processing ${file.fileName}:`, error.message);
      await storage.updateRawXmlStatus(file.id, 'error', error.message);
    }
  }
  
  console.log('============================================================');
  console.log('✨ Parser test complete!');
  console.log('============================================================');
}

testParser().catch(console.error).finally(() => process.exit());
