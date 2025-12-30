// Temporary script to query production database
const { Pool } = require('pg');

const productionPool = new Pool({
  connectionString: process.env.PRODUCTION_DATABASE_URL,
});

async function checkProduction() {
  try {
    console.log('=== PRODUCTION DATABASE CHECK ===\n');
    
    // 1. Total records
    const totalResult = await productionPool.query(
      'SELECT COUNT(*) as total, MAX(id) as max_id FROM sales_raw_xml'
    );
    console.log('Total Records:', totalResult.rows[0]);
    
    // 2. Store 1320 raw XML files
    console.log('\n=== STORE 1320 RAW XML FILES ===');
    const store1320Files = await productionPool.query(`
      SELECT 
        id,
        report_type,
        business_date,
        file_name,
        processing_status,
        error_message,
        uploaded_at
      FROM sales_raw_xml
      WHERE pdi_store_number = '1320'
      ORDER BY id
    `);
    
    if (store1320Files.rows.length === 0) {
      console.log('⚠️  NO FILES FOUND FOR STORE 1320');
    } else {
      store1320Files.rows.forEach(row => {
        console.log(`ID ${row.id}: ${row.report_type} | ${row.file_name}`);
        console.log(`  Status: ${row.processing_status} | Date: ${row.business_date}`);
        if (row.error_message) {
          console.log(`  Error: ${row.error_message}`);
        }
      });
    }
    
    // 3. Check parsed fuel grades for Store 1320
    console.log('\n=== STORE 1320 PARSED FUEL GRADES ===');
    const fuelGrades = await productionPool.query(`
      SELECT 
        business_date,
        grade_id,
        grade_name,
        volume,
        amount
      FROM sales_fuel_grades
      WHERE pdi_store_number = '1320'
      ORDER BY business_date DESC
      LIMIT 10
    `);
    
    if (fuelGrades.rows.length === 0) {
      console.log('⚠️  NO PARSED FUEL GRADES FOUND');
    } else {
      fuelGrades.rows.forEach(row => {
        console.log(`${row.business_date} | ${row.grade_name}: ${row.volume} gal, $${row.amount}`);
      });
    }
    
    // 4. Check parsed transactions for Store 1320
    console.log('\n=== STORE 1320 PARSED TRANSACTIONS ===');
    const transactions = await productionPool.query(`
      SELECT 
        business_date,
        COUNT(*) as transaction_count,
        SUM(fuel_volume) as total_fuel_volume,
        SUM(fuel_amount) as total_fuel_amount,
        SUM(merch_amount) as total_merch_amount
      FROM sales_transactions
      WHERE pdi_store_number = '1320'
      GROUP BY business_date
      ORDER BY business_date DESC
      LIMIT 10
    `);
    
    if (transactions.rows.length === 0) {
      console.log('⚠️  NO PARSED TRANSACTIONS FOUND');
    } else {
      transactions.rows.forEach(row => {
        console.log(`${row.business_date}: ${row.transaction_count} trans | Fuel: ${row.total_fuel_volume} gal, $${row.total_fuel_amount} | Merch: $${row.total_merch_amount}`);
      });
    }
    
    // 5. Summary by store and type
    console.log('\n=== ALL STORES FILE SUMMARY ===');
    const summary = await productionPool.query(`
      SELECT 
        pdi_store_number,
        report_type,
        COUNT(*) as file_count,
        SUM(CASE WHEN processing_status = 'processed' THEN 1 ELSE 0 END) as processed_count,
        SUM(CASE WHEN processing_status = 'pending' THEN 1 ELSE 0 END) as pending_count,
        SUM(CASE WHEN processing_status = 'error' THEN 1 ELSE 0 END) as error_count
      FROM sales_raw_xml
      GROUP BY pdi_store_number, report_type
      ORDER BY pdi_store_number, report_type
    `);
    
    summary.rows.forEach(row => {
      console.log(`Store ${row.pdi_store_number} ${row.report_type}: ${row.file_count} total (${row.processed_count} processed, ${row.pending_count} pending, ${row.error_count} errors)`);
    });
    
  } catch (error) {
    console.log('Error querying production database:', error);
  } finally {
    await productionPool.end();
  }
}

checkProduction();
