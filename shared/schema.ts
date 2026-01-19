import { pgTable, serial, varchar, integer, timestamp, text, boolean, numeric } from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  firstName: varchar('first_name', { length: 100 }).notNull(),
  lastName: varchar('last_name', { length: 100 }).notNull(),
  email: varchar('email', { length: 255 }).unique(),
  phone: varchar('phone', { length: 20 }).notNull(),
  dateOfBirth: varchar('date_of_birth', { length: 20 }).notNull(),
  zipCode: varchar('zip_code', { length: 10 }),
  password: varchar('password', { length: 255 }),
  pin: varchar('pin', { length: 4 }),
  accountNumber: varchar('account_number', { length: 18 }).notNull().unique(),
  loyaltyId: varchar('loyalty_id', { length: 22 }).notNull().unique(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const rewards = pgTable('rewards', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id),
  points: integer('points').notNull().default(0),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const transactions = pgTable('transactions', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id),
  points: integer('points').notNull(),
  description: text('description').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const adminUsers = pgTable('admin_users', {
  id: serial('id').primaryKey(),
  firstName: varchar('first_name', { length: 100 }).notNull(),
  lastName: varchar('last_name', { length: 100 }).notNull(),
  email: varchar('email', { length: 255 }).notNull().unique(),
  phone: varchar('phone', { length: 20 }).notNull(),
  password: varchar('password', { length: 255 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const passwordResetTokens = pgTable('password_reset_tokens', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id),
  token: varchar('token', { length: 64 }).notNull().unique(),
  expiresAt: timestamp('expires_at').notNull(),
  used: boolean('used').default(false).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const locations = pgTable('locations', {
  id: serial('id').primaryKey(),
  locationName: varchar('location_name', { length: 255 }).notNull(),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull().unique(),
  posId: varchar('pos_id', { length: 50 }),
  address1: varchar('address_1', { length: 255 }).notNull(),
  address2: varchar('address_2', { length: 255 }),
  city: varchar('city', { length: 100 }).notNull(),
  state: varchar('state', { length: 50 }).notNull(),
  zipCode: varchar('zip_code', { length: 20 }).notNull(),
  posType: varchar('pos_type', { length: 50 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const itemGroups = pgTable('item_groups', {
  id: serial('id').primaryKey(),
  name: varchar('name', { length: 255 }).notNull(),
  description: text('description'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const itemGroupUpcs = pgTable('item_group_upcs', {
  id: serial('id').primaryKey(),
  itemGroupId: integer('item_group_id').notNull().references(() => itemGroups.id, { onDelete: 'cascade' }),
  upc: varchar('upc', { length: 50 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const promotions = pgTable('promotions', {
  id: serial('id').primaryKey(),
  name: varchar('name', { length: 100 }),
  itemGroupId: integer('item_group_id').notNull().references(() => itemGroups.id, { onDelete: 'cascade' }),
  quantity: integer('quantity').notNull(),
  freeQuantity: integer('free_quantity'),
  discountType: varchar('discount_type', { length: 20 }).notNull().default('multipack'),
  price: numeric('price', { precision: 10, scale: 2 }),
  amountOff: numeric('amount_off', { precision: 10, scale: 2 }),
  requiresLoyaltyId: boolean('requires_loyalty_id').notNull().default(false),
  isActive: boolean('is_active').notNull().default(true),
  startDate: timestamp('start_date'),
  endDate: timestamp('end_date'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const promotionLocations = pgTable('promotion_locations', {
  id: serial('id').primaryKey(),
  promotionId: integer('promotion_id').notNull().references(() => promotions.id, { onDelete: 'cascade' }),
  locationId: integer('location_id').notNull().references(() => locations.id, { onDelete: 'cascade' }),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const pricebook = pgTable('pricebook', {
  id: serial('id').primaryKey(),
  upc: varchar('upc', { length: 50 }).notNull().unique(),
  description: varchar('description', { length: 255 }).notNull(),
  sku: varchar('sku', { length: 50 }),
  unit: varchar('unit', { length: 20 }),
  price: numeric('price', { precision: 10, scale: 2 }),
  category: varchar('category', { length: 50 }),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const posPresence = pgTable('pos_presence', {
  id: serial('id').primaryKey(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  posId: varchar('pos_id', { length: 50 }),
  posType: varchar('pos_type', { length: 50 }).notNull(),
  posIpAddress: varchar('pos_ip_address', { length: 50 }),
  edgeIpAddress: varchar('edge_ip_address', { length: 50 }),
  edgeVersion: varchar('edge_version', { length: 50 }),
  status: varchar('status', { length: 20 }).notNull().default('online'),
  lastSeen: timestamp('last_seen').notNull().defaultNow(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// ============================================
// SALES ANALYTICS TABLES
// ============================================

export const salesRawXml = pgTable('sales_raw_xml', {
  id: serial('id').primaryKey(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  reportType: varchar('report_type', { length: 20 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  fileName: varchar('file_name', { length: 255 }).notNull(),
  xmlContent: text('xml_content').notNull(),
  fileSize: integer('file_size').notNull(),
  uploadedAt: timestamp('uploaded_at').defaultNow().notNull(),
  processedAt: timestamp('processed_at'),
  processingStatus: varchar('processing_status', { length: 20 }).notNull().default('pending'),
  errorMessage: text('error_message'),
});

export const salesTransactions = pgTable('sales_transactions', {
  id: serial('id').primaryKey(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  transactionId: varchar('transaction_id', { length: 100 }).notNull(),
  transactionDateTime: timestamp('transaction_datetime').notNull(),
  cashierId: varchar('cashier_id', { length: 50 }),
  fuelVolume: numeric('fuel_volume', { precision: 10, scale: 3 }).default('0'),
  fuelAmount: numeric('fuel_amount', { precision: 10, scale: 2 }).default('0'),
  merchAmount: numeric('merch_amount', { precision: 10, scale: 2 }).default('0'),
  totalAmount: numeric('total_amount', { precision: 10, scale: 2 }).notNull(),
  tenderType: varchar('tender_type', { length: 50 }),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const salesLineItems = pgTable('sales_line_items', {
  id: serial('id').primaryKey(),
  posTransactionId: varchar('pos_transaction_id', { length: 100 }).notNull(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  itemType: varchar('item_type', { length: 20 }).notNull(),
  upc: varchar('upc', { length: 50 }),
  description: varchar('description', { length: 255 }),
  pumpNumber: varchar('pump_number', { length: 10 }),
  quantity: numeric('quantity', { precision: 10, scale: 3 }).notNull(),
  amount: numeric('amount', { precision: 10, scale: 2 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const salesFuelGrades = pgTable('sales_fuel_grades', {
  id: serial('id').primaryKey(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  gradeId: varchar('grade_id', { length: 50 }).notNull(),
  gradeName: varchar('grade_name', { length: 100 }),
  volume: numeric('volume', { precision: 10, scale: 3 }).notNull(),
  amount: numeric('amount', { precision: 10, scale: 2 }).notNull(),
  discountAmount: numeric('discount_amount', { precision: 10, scale: 2 }).default('0'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const salesItems = pgTable('sales_items', {
  id: serial('id').primaryKey(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  upc: varchar('upc', { length: 50 }).notNull(),
  description: varchar('description', { length: 255 }),
  quantity: numeric('quantity', { precision: 10, scale: 3 }).notNull(),
  salesAmount: numeric('sales_amount', { precision: 10, scale: 2 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const salesDepartments = pgTable('sales_departments', {
  id: serial('id').primaryKey(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  departmentCode: varchar('department_code', { length: 50 }).notNull(),
  departmentName: varchar('department_name', { length: 255 }),
  salesAmount: numeric('sales_amount', { precision: 10, scale: 2 }).notNull(),
  quantity: numeric('quantity', { precision: 10, scale: 3 }).notNull(),
  transactionCount: integer('transaction_count').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const salesLoyaltyUsage = pgTable('sales_loyalty_usage', {
  id: serial('id').primaryKey(),
  posTransactionId: varchar('pos_transaction_id', { length: 100 }).notNull(),
  locationId: integer('location_id').references(() => locations.id, { onDelete: 'cascade' }),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  businessDate: varchar('business_date', { length: 10 }).notNull(),
  promotionId: varchar('promotion_id', { length: 100 }),
  promotionAmount: numeric('promotion_amount', { precision: 10, scale: 2 }).notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// ============================================
// BIRDIES LOYALTY TABLES (Live TCP Data)
// ============================================

export const loyaltyTransactions = pgTable('loyalty_transactions', {
  id: serial('id').primaryKey(),
  transactionId: varchar('transaction_id', { length: 100 }).notNull(),
  transactionDate: timestamp('transaction_date').notNull(),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  customerId: integer('customer_id').references(() => users.id),
  customerName: varchar('customer_name', { length: 200 }),
  loyaltyId: varchar('loyalty_id', { length: 22 }),
  subtotal: numeric('subtotal', { precision: 10, scale: 2 }).notNull(),
  promotionDiscount: numeric('promotion_discount', { precision: 10, scale: 2 }).default('0'),
  pointsDiscount: numeric('points_discount', { precision: 10, scale: 2 }).default('0'),
  totalDiscount: numeric('total_discount', { precision: 10, scale: 2 }).default('0'),
  netAmount: numeric('net_amount', { precision: 10, scale: 2 }).notNull(),
  pointsBefore: integer('points_before').default(0),
  pointsEarned: integer('points_earned').default(0),
  pointsRedeemed: integer('points_redeemed').default(0),
  pointsAfter: integer('points_after').default(0),
  promotionUsed: boolean('promotion_used').default(false),
  promotionCount: integer('promotion_count').default(0),
  promotionNames: text('promotion_names'),
  promotionDetails: text('promotion_details'),
  lineItems: text('line_items'),
  itemCount: integer('item_count').default(0),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const loyaltyFailedLookups = pgTable('loyalty_failed_lookups', {
  id: serial('id').primaryKey(),
  lookupDate: timestamp('lookup_date').notNull(),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }).notNull(),
  inputType: varchar('input_type', { length: 20 }).notNull(),
  inputValue: varchar('input_value', { length: 100 }).notNull(),
  errorReason: varchar('error_reason', { length: 255 }),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// ============================================
// PUNCH CARD TABLES (Loyalty Punch Cards)
// ============================================

export const punchCardPromotions = pgTable('punch_card_promotions', {
  id: serial('id').primaryKey(),
  name: varchar('name', { length: 255 }).notNull(),
  itemGroupId: integer('item_group_id').references(() => itemGroups.id, { onDelete: 'cascade' }).notNull(),
  punchesRequired: integer('punches_required').notNull().default(10),
  rewardType: varchar('reward_type', { length: 50 }).notNull().default('free_item'),
  rewardValue: numeric('reward_value', { precision: 10, scale: 2 }),
  isActive: boolean('is_active').default(true),
  startDate: timestamp('start_date'),
  endDate: timestamp('end_date'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const customerPunches = pgTable('customer_punches', {
  id: serial('id').primaryKey(),
  customerId: integer('customer_id').references(() => users.id, { onDelete: 'cascade' }).notNull(),
  punchCardId: integer('punch_card_id').references(() => punchCardPromotions.id, { onDelete: 'cascade' }).notNull(),
  currentPunches: integer('current_punches').notNull().default(0),
  totalPunchesEarned: integer('total_punches_earned').notNull().default(0),
  totalRewardsRedeemed: integer('total_rewards_redeemed').notNull().default(0),
  lastPunchDate: timestamp('last_punch_date'),
  lastRewardDate: timestamp('last_reward_date'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const punchCardHistory = pgTable('punch_card_history', {
  id: serial('id').primaryKey(),
  customerId: integer('customer_id').references(() => users.id, { onDelete: 'cascade' }).notNull(),
  punchCardId: integer('punch_card_id').references(() => punchCardPromotions.id, { onDelete: 'cascade' }).notNull(),
  pdiStoreNumber: varchar('pdi_store_number', { length: 50 }),
  actionType: varchar('action_type', { length: 20 }).notNull(),
  punchesChanged: integer('punches_changed').notNull(),
  punchesBefore: integer('punches_before').notNull(),
  punchesAfter: integer('punches_after').notNull(),
  upc: varchar('upc', { length: 50 }),
  transactionId: varchar('transaction_id', { length: 100 }),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const usersRelations = relations(users, ({ one, many }) => ({
  rewards: one(rewards, {
    fields: [users.id],
    references: [rewards.userId],
  }),
  transactions: many(transactions),
}));

export const rewardsRelations = relations(rewards, ({ one }) => ({
  user: one(users, {
    fields: [rewards.userId],
    references: [users.id],
  }),
}));

export const transactionsRelations = relations(transactions, ({ one }) => ({
  user: one(users, {
    fields: [transactions.userId],
    references: [users.id],
  }),
}));

export const itemGroupsRelations = relations(itemGroups, ({ many }) => ({
  upcs: many(itemGroupUpcs),
  promotions: many(promotions),
}));

export const itemGroupUpcsRelations = relations(itemGroupUpcs, ({ one }) => ({
  itemGroup: one(itemGroups, {
    fields: [itemGroupUpcs.itemGroupId],
    references: [itemGroups.id],
  }),
}));

export const promotionsRelations = relations(promotions, ({ one, many }) => ({
  itemGroup: one(itemGroups, {
    fields: [promotions.itemGroupId],
    references: [itemGroups.id],
  }),
  locations: many(promotionLocations),
}));

export const promotionLocationsRelations = relations(promotionLocations, ({ one }) => ({
  promotion: one(promotions, {
    fields: [promotionLocations.promotionId],
    references: [promotions.id],
  }),
  location: one(locations, {
    fields: [promotionLocations.locationId],
    references: [locations.id],
  }),
}));

export const locationsRelations = relations(locations, ({ many }) => ({
  promotions: many(promotionLocations),
}));

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;
export type AdminUser = typeof adminUsers.$inferSelect;
export type InsertAdminUser = typeof adminUsers.$inferInsert;
export type Reward = typeof rewards.$inferSelect;
export type InsertReward = typeof rewards.$inferInsert;
export type Transaction = typeof transactions.$inferSelect;
export type InsertTransaction = typeof transactions.$inferInsert;
export type Location = typeof locations.$inferSelect;
export type InsertLocation = typeof locations.$inferInsert;
export type ItemGroup = typeof itemGroups.$inferSelect;
export type InsertItemGroup = typeof itemGroups.$inferInsert;
export type ItemGroupUpc = typeof itemGroupUpcs.$inferSelect;
export type InsertItemGroupUpc = typeof itemGroupUpcs.$inferInsert;
export type Promotion = typeof promotions.$inferSelect;
export type InsertPromotion = typeof promotions.$inferInsert;
export type PromotionLocation = typeof promotionLocations.$inferSelect;
export type InsertPromotionLocation = typeof promotionLocations.$inferInsert;
export type PricebookItem = typeof pricebook.$inferSelect;
export type InsertPricebookItem = typeof pricebook.$inferInsert;

export type SalesRawXml = typeof salesRawXml.$inferSelect;
export type InsertSalesRawXml = typeof salesRawXml.$inferInsert;
export type SalesTransaction = typeof salesTransactions.$inferSelect;
export type InsertSalesTransaction = typeof salesTransactions.$inferInsert;
export type SalesLineItem = typeof salesLineItems.$inferSelect;
export type InsertSalesLineItem = typeof salesLineItems.$inferInsert;
export type SalesFuelGrade = typeof salesFuelGrades.$inferSelect;
export type InsertSalesFuelGrade = typeof salesFuelGrades.$inferInsert;
export type SalesItem = typeof salesItems.$inferSelect;
export type InsertSalesItem = typeof salesItems.$inferInsert;
export type SalesDepartment = typeof salesDepartments.$inferSelect;
export type InsertSalesDepartment = typeof salesDepartments.$inferInsert;
export type SalesLoyaltyUsage = typeof salesLoyaltyUsage.$inferSelect;
export type InsertSalesLoyaltyUsage = typeof salesLoyaltyUsage.$inferInsert;

export type LoyaltyTransaction = typeof loyaltyTransactions.$inferSelect;
export type InsertLoyaltyTransaction = typeof loyaltyTransactions.$inferInsert;
export type LoyaltyFailedLookup = typeof loyaltyFailedLookups.$inferSelect;
export type InsertLoyaltyFailedLookup = typeof loyaltyFailedLookups.$inferInsert;

export type PunchCardPromotion = typeof punchCardPromotions.$inferSelect;
export type InsertPunchCardPromotion = typeof punchCardPromotions.$inferInsert;
export type CustomerPunch = typeof customerPunches.$inferSelect;
export type InsertCustomerPunch = typeof customerPunches.$inferInsert;
export type PunchCardHistory = typeof punchCardHistory.$inferSelect;
export type InsertPunchCardHistory = typeof punchCardHistory.$inferInsert;

export const jobApplications = pgTable('job_applications', {
  id: serial('id').primaryKey(),
  firstName: varchar('first_name', { length: 100 }).notNull(),
  lastName: varchar('last_name', { length: 100 }).notNull(),
  phone: varchar('phone', { length: 20 }).notNull(),
  email: varchar('email', { length: 255 }).notNull(),
  isOver18: boolean('is_over_18').notNull(),
  position: varchar('position', { length: 100 }).notNull(),
  employmentType: varchar('employment_type', { length: 50 }).notNull(),
  availableShifts: text('available_shifts').notNull(),
  startDate: varchar('start_date', { length: 50 }).notNull(),
  previousExperience: text('previous_experience'),
  retailExperience: boolean('retail_experience').default(false),
  authorizedToWork: boolean('authorized_to_work').notNull(),
  canLiftAndStand: boolean('can_lift_and_stand').notNull(),
  whyWorkHere: text('why_work_here'),
  referralSource: varchar('referral_source', { length: 100 }),
  storeLocation: varchar('store_location', { length: 255 }),
  status: varchar('status', { length: 50 }).default('new').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export type JobApplication = typeof jobApplications.$inferSelect;
export type InsertJobApplication = typeof jobApplications.$inferInsert;
