import { readFileSync } from 'fs';
import { parse } from 'csv-parse/sync';
import { db } from './db';
import { pricebook } from '../shared/schema';
import { sql } from 'drizzle-orm';

async function importPricebook() {
  try {
    console.log('Truncating existing pricebook data...');
    await db.execute(sql`TRUNCATE TABLE pricebook RESTART IDENTITY CASCADE`);
    
    const csvContent = readFileSync('attached_assets/CONSOLIDATED PB NSR MD BY SITE OCT 07 2025_1759936366368.csv', 'utf-8');
    
    const records = parse(csvContent, {
      skip_empty_lines: true,
    });

    const uniqueItems = new Map();
    
    for (const record of records) {
      let upc = String(record[8] || '').trim();
      const description = record[5]?.trim();
      const sku = record[4]?.trim();
      const unit = record[6]?.trim();
      const price = record[27]?.trim();
      
      if (upc && upc !== '0' && description && upc.length > 0) {
        while (upc.length < 12) {
          upc = '0' + upc;
        }
        
        const key = `${upc}_${description}`;
        if (!uniqueItems.has(key)) {
          uniqueItems.set(key, {
            upc,
            description,
            sku: sku || null,
            unit: unit || null,
            price: price ? price : null,
          });
        }
      }
    }

    const itemsToInsert = Array.from(uniqueItems.values());
    
    console.log(`Importing ${itemsToInsert.length} unique items from pricebook...`);
    
    const batchSize = 500;
    for (let i = 0; i < itemsToInsert.length; i += batchSize) {
      const batch = itemsToInsert.slice(i, i + batchSize);
      await db.insert(pricebook).values(batch);
      console.log(`Imported ${Math.min(i + batchSize, itemsToInsert.length)} / ${itemsToInsert.length} items`);
    }
    
    console.log('Pricebook import completed successfully!');
  } catch (error) {
    console.error('Error importing pricebook:', error);
    process.exit(1);
  }
  
  process.exit(0);
}

importPricebook();
