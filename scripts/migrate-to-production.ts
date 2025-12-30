#!/usr/bin/env tsx
/**
 * Migration script to copy data from development database to production database
 * 
 * Usage: 
 * 1. Set PRODUCTION_DATABASE_URL environment variable
 * 2. Run: npx tsx scripts/migrate-to-production.ts
 */

import { drizzle } from 'drizzle-orm/neon-serverless';
import { neonConfig, Pool } from '@neondatabase/serverless';
import ws from 'ws';
import * as schema from '../shared/schema';

// Configure WebSocket for Neon
neonConfig.webSocketConstructor = ws;

const DEV_DATABASE_URL = process.env.DATABASE_URL;
const PROD_DATABASE_URL = process.env.PRODUCTION_DATABASE_URL;

if (!DEV_DATABASE_URL) {
  console.log('❌ DATABASE_URL not set (development database)');
  process.exit(1);
}

if (!PROD_DATABASE_URL) {
  console.log('❌ PRODUCTION_DATABASE_URL not set');
  console.log('Please set it to your production database URL');
  process.exit(1);
}

console.log('🚀 Starting data migration from development to production...\n');

async function migrate() {
  // Connect to both databases
  const devPool = new Pool({ connectionString: DEV_DATABASE_URL });
  const prodPool = new Pool({ connectionString: PROD_DATABASE_URL });
  
  const devDb = drizzle(devPool, { schema });
  const prodDb = drizzle(prodPool, { schema });

  try {
    // 1. Migrate Pricebook
    console.log('📦 Migrating pricebook...');
    const pricebookItems = await devDb.select().from(schema.pricebook);
    if (pricebookItems.length > 0) {
      await prodDb.insert(schema.pricebook).values(pricebookItems).onConflictDoNothing();
      console.log(`   ✅ Migrated ${pricebookItems.length} pricebook items`);
    }

    // 2. Migrate Locations
    console.log('📍 Migrating locations...');
    const locations = await devDb.select().from(schema.locations);
    if (locations.length > 0) {
      await prodDb.insert(schema.locations).values(locations).onConflictDoNothing();
      console.log(`   ✅ Migrated ${locations.length} locations`);
    }

    // 3. Migrate Admin Users
    console.log('👤 Migrating admin users...');
    const adminUsers = await devDb.select().from(schema.adminUsers);
    if (adminUsers.length > 0) {
      await prodDb.insert(schema.adminUsers).values(adminUsers).onConflictDoNothing();
      console.log(`   ✅ Migrated ${adminUsers.length} admin users`);
    }

    // 4. Migrate Users (Customers)
    console.log('👥 Migrating customers...');
    const users = await devDb.select().from(schema.users);
    if (users.length > 0) {
      await prodDb.insert(schema.users).values(users).onConflictDoNothing();
      console.log(`   ✅ Migrated ${users.length} customers`);
    }

    // 5. Migrate Rewards
    console.log('🎁 Migrating rewards...');
    const rewards = await devDb.select().from(schema.rewards);
    if (rewards.length > 0) {
      await prodDb.insert(schema.rewards).values(rewards).onConflictDoNothing();
      console.log(`   ✅ Migrated ${rewards.length} reward records`);
    }

    // 6. Migrate Transactions
    console.log('💳 Migrating transactions...');
    const transactions = await devDb.select().from(schema.transactions);
    if (transactions.length > 0) {
      await prodDb.insert(schema.transactions).values(transactions).onConflictDoNothing();
      console.log(`   ✅ Migrated ${transactions.length} transactions`);
    }

    // 7. Migrate Item Groups
    console.log('📦 Migrating item groups...');
    const itemGroups = await devDb.select().from(schema.itemGroups);
    if (itemGroups.length > 0) {
      await prodDb.insert(schema.itemGroups).values(itemGroups).onConflictDoNothing();
      console.log(`   ✅ Migrated ${itemGroups.length} item groups`);
    }

    // 8. Migrate Item Group UPCs
    console.log('🏷️  Migrating item group UPCs...');
    const itemGroupUpcs = await devDb.select().from(schema.itemGroupUpcs);
    if (itemGroupUpcs.length > 0) {
      await prodDb.insert(schema.itemGroupUpcs).values(itemGroupUpcs).onConflictDoNothing();
      console.log(`   ✅ Migrated ${itemGroupUpcs.length} item group UPC associations`);
    }

    // 9. Migrate Promotions
    console.log('🎯 Migrating promotions...');
    const promotions = await devDb.select().from(schema.promotions);
    if (promotions.length > 0) {
      await prodDb.insert(schema.promotions).values(promotions).onConflictDoNothing();
      console.log(`   ✅ Migrated ${promotions.length} promotions`);
    }

    // 10. Migrate Promotion Locations
    console.log('📍 Migrating promotion locations...');
    const promotionLocations = await devDb.select().from(schema.promotionLocations);
    if (promotionLocations.length > 0) {
      await prodDb.insert(schema.promotionLocations).values(promotionLocations).onConflictDoNothing();
      console.log(`   ✅ Migrated ${promotionLocations.length} promotion location associations`);
    }

    console.log('\n✅ Migration completed successfully!');
    console.log('\n📊 Summary:');
    console.log(`   - Pricebook: ${pricebookItems.length} items`);
    console.log(`   - Locations: ${locations.length} stores`);
    console.log(`   - Customers: ${users.length} users`);
    console.log(`   - Rewards: ${rewards.length} records`);
    console.log(`   - Transactions: ${transactions.length} records`);
    console.log(`   - Item Groups: ${itemGroups.length} groups`);
    console.log(`   - Promotions: ${promotions.length} promotions`);

  } catch (error) {
    console.log('\n❌ Migration failed:', error);
    process.exit(1);
  } finally {
    await devPool.end();
    await prodPool.end();
  }
}

migrate();
