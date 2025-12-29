import { users, rewards, transactions, locations, adminUsers, itemGroups, itemGroupUpcs, promotions, promotionLocations, pricebook, posPresence, salesRawXml, salesTransactions, salesLineItems, salesFuelGrades, salesItems, salesDepartments, salesLoyaltyUsage, type User, type InsertUser, type AdminUser, type InsertAdminUser, type Reward, type Transaction, type InsertTransaction, type Location, type InsertLocation, type ItemGroup, type InsertItemGroup, type ItemGroupUpc, type InsertItemGroupUpc, type Promotion, type InsertPromotion, type PromotionLocation, type InsertPromotionLocation, type PricebookItem, type SalesRawXml, type InsertSalesRawXml, type SalesTransaction, type InsertSalesTransaction, type SalesLineItem, type InsertSalesLineItem, type SalesFuelGrade, type InsertSalesFuelGrade, type SalesItem, type InsertSalesItem, type SalesDepartment, type InsertSalesDepartment, type SalesLoyaltyUsage, type InsertSalesLoyaltyUsage } from "../shared/schema";
import { db } from "./db";
import { eq, desc, ilike, or, sql, and } from "drizzle-orm";

export class DatabaseStorage {
  async getUserByEmail(email: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.email, email));
    return user || undefined;
  }

  async getUserById(id: number): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user || undefined;
  }

  async getUserByLoyaltyId(loyaltyId: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.loyaltyId, loyaltyId));
    return user || undefined;
  }

  async getUserByPhone(phone: string): Promise<User | undefined> {
    // Normalize phone number by removing all non-digit characters
    const normalizedInput = phone.replace(/\D/g, '');
    
    // Search for phone with normalized comparison
    const [user] = await db
      .select()
      .from(users)
      .where(sql`REGEXP_REPLACE(${users.phone}, '[^0-9]', '', 'g') = ${normalizedInput}`)
      .limit(1);
    
    return user || undefined;
  }

  async createUser(insertUser: InsertUser): Promise<User> {
    const [user] = await db
      .insert(users)
      .values(insertUser)
      .returning();
    
    await db.insert(rewards).values({
      userId: user.id,
      points: 0,
    });
    
    return user;
  }

  async getUserRewards(userId: number): Promise<Reward | undefined> {
    const [reward] = await db.select().from(rewards).where(eq(rewards.userId, userId));
    return reward || undefined;
  }

  async getUserTransactions(userId: number): Promise<Transaction[]> {
    const userTransactions = await db
      .select()
      .from(transactions)
      .where(eq(transactions.userId, userId))
      .orderBy(desc(transactions.createdAt));
    return userTransactions;
  }

  async addRewardPoints(userId: number, points: number, description: string): Promise<void> {
    await db.transaction(async (tx) => {
      const [currentReward] = await tx.select().from(rewards).where(eq(rewards.userId, userId));
      
      if (currentReward) {
        await tx
          .update(rewards)
          .set({ 
            points: currentReward.points + points,
            updatedAt: new Date()
          })
          .where(eq(rewards.userId, userId));
      }
      
      await tx.insert(transactions).values({
        userId,
        points,
        description,
      });
    });
  }

  async getAllUsers(): Promise<User[]> {
    const allUsers = await db.select().from(users).orderBy(desc(users.createdAt));
    return allUsers;
  }

  async updateUser(id: number, updates: Partial<InsertUser>): Promise<User | undefined> {
    const [updatedUser] = await db
      .update(users)
      .set(updates)
      .where(eq(users.id, id))
      .returning();
    return updatedUser || undefined;
  }

  async getAdminByEmail(email: string): Promise<AdminUser | undefined> {
    const [admin] = await db.select().from(adminUsers).where(eq(adminUsers.email, email));
    return admin || undefined;
  }

  async getAdminById(id: number): Promise<AdminUser | undefined> {
    const [admin] = await db.select().from(adminUsers).where(eq(adminUsers.id, id));
    return admin || undefined;
  }

  async createAdminUser(insertAdmin: InsertAdminUser): Promise<AdminUser> {
    const [admin] = await db
      .insert(adminUsers)
      .values(insertAdmin)
      .returning();
    return admin;
  }

  async getAllAdminUsers(): Promise<AdminUser[]> {
    const allAdmins = await db.select().from(adminUsers).orderBy(desc(adminUsers.createdAt));
    return allAdmins;
  }

  async updateAdminUser(id: number, updates: Partial<InsertAdminUser>): Promise<AdminUser | undefined> {
    const [updatedAdmin] = await db
      .update(adminUsers)
      .set(updates)
      .where(eq(adminUsers.id, id))
      .returning();
    return updatedAdmin || undefined;
  }

  async getAllLocations(): Promise<Location[]> {
    const allLocations = await db.select().from(locations).orderBy(desc(locations.createdAt));
    return allLocations;
  }

  async getLocationById(id: number): Promise<Location | undefined> {
    const [location] = await db.select().from(locations).where(eq(locations.id, id));
    return location || undefined;
  }

  async getLocationByPdiStoreNumber(pdiStoreNumber: string): Promise<Location | undefined> {
    const [location] = await db.select().from(locations).where(eq(locations.pdiStoreNumber, pdiStoreNumber));
    return location || undefined;
  }

  async createLocation(insertLocation: InsertLocation): Promise<Location> {
    const [location] = await db
      .insert(locations)
      .values(insertLocation)
      .returning();
    return location;
  }

  async updateLocation(id: number, updates: Partial<InsertLocation>): Promise<Location | undefined> {
    const [updatedLocation] = await db
      .update(locations)
      .set(updates)
      .where(eq(locations.id, id))
      .returning();
    return updatedLocation || undefined;
  }

  async deleteLocation(id: number): Promise<void> {
    await db.delete(locations).where(eq(locations.id, id));
  }

  async getAllItemGroups(): Promise<any[]> {
    const allItemGroups = await db
      .select({
        id: itemGroups.id,
        name: itemGroups.name,
        description: itemGroups.description,
        createdAt: itemGroups.createdAt,
        upcCount: sql<number>`(SELECT COUNT(*) FROM ${itemGroupUpcs} WHERE ${itemGroupUpcs.itemGroupId} = ${itemGroups.id})`,
      })
      .from(itemGroups)
      .orderBy(desc(itemGroups.createdAt));
    return allItemGroups;
  }

  async getItemGroupById(id: number): Promise<ItemGroup | undefined> {
    const [itemGroup] = await db.select().from(itemGroups).where(eq(itemGroups.id, id));
    return itemGroup || undefined;
  }

  async createItemGroup(insertItemGroup: InsertItemGroup): Promise<ItemGroup> {
    const existing = await db
      .select()
      .from(itemGroups)
      .where(eq(itemGroups.name, insertItemGroup.name));
    
    if (existing.length > 0) {
      throw new Error('Item group with this name already exists');
    }

    const [itemGroup] = await db
      .insert(itemGroups)
      .values(insertItemGroup)
      .returning();
    return itemGroup;
  }

  async updateItemGroup(id: number, updates: Partial<InsertItemGroup>): Promise<ItemGroup | undefined> {
    if (updates.name) {
      const existing = await db
        .select()
        .from(itemGroups)
        .where(
          and(
            eq(itemGroups.name, updates.name),
            sql`${itemGroups.id} != ${id}`
          )
        );
      
      if (existing.length > 0) {
        throw new Error('Item group with this name already exists');
      }
    }

    const [updatedItemGroup] = await db
      .update(itemGroups)
      .set(updates)
      .where(eq(itemGroups.id, id))
      .returning();
    return updatedItemGroup || undefined;
  }

  async deleteItemGroup(id: number): Promise<void> {
    await db.delete(itemGroups).where(eq(itemGroups.id, id));
  }

  async getItemGroupUpcs(itemGroupId: number): Promise<any[]> {
    const upcs = await db
      .select({
        id: itemGroupUpcs.id,
        itemGroupId: itemGroupUpcs.itemGroupId,
        upc: itemGroupUpcs.upc,
        createdAt: itemGroupUpcs.createdAt,
        description: pricebook.description,
      })
      .from(itemGroupUpcs)
      .leftJoin(pricebook, eq(itemGroupUpcs.upc, pricebook.upc))
      .where(eq(itemGroupUpcs.itemGroupId, itemGroupId))
      .orderBy(desc(itemGroupUpcs.createdAt));
    return upcs;
  }

  async addUpcToItemGroup(insertUpc: InsertItemGroupUpc): Promise<ItemGroupUpc> {
    const existing = await db
      .select()
      .from(itemGroupUpcs)
      .where(
        and(
          eq(itemGroupUpcs.itemGroupId, insertUpc.itemGroupId),
          eq(itemGroupUpcs.upc, insertUpc.upc)
        )
      );
    
    if (existing.length > 0) {
      throw new Error('UPC already exists in this item group');
    }

    const [upc] = await db
      .insert(itemGroupUpcs)
      .values(insertUpc)
      .returning();
    return upc;
  }

  async deleteItemGroupUpc(id: number): Promise<void> {
    await db.delete(itemGroupUpcs).where(eq(itemGroupUpcs.id, id));
  }

  async deleteItemGroupUpcByCode(itemGroupId: number, upc: string): Promise<void> {
    await db
      .delete(itemGroupUpcs)
      .where(
        and(
          eq(itemGroupUpcs.itemGroupId, itemGroupId),
          eq(itemGroupUpcs.upc, upc)
        )
      );
  }

  async getAllPromotions(): Promise<any[]> {
    const allPromotions = await db
      .select({
        id: promotions.id,
        itemGroupId: promotions.itemGroupId,
        itemGroupName: itemGroups.name,
        quantity: promotions.quantity,
        discountType: promotions.discountType,
        price: promotions.price,
        amountOff: promotions.amountOff,
        requiresLoyaltyId: promotions.requiresLoyaltyId,
        isActive: promotions.isActive,
        startDate: promotions.startDate,
        endDate: promotions.endDate,
        createdAt: promotions.createdAt,
      })
      .from(promotions)
      .leftJoin(itemGroups, eq(promotions.itemGroupId, itemGroups.id))
      .orderBy(desc(promotions.createdAt));
    return allPromotions;
  }

  async getActivePromotionsForLocation(locationId: number): Promise<any[]> {
    const now = new Date();
    
    const activePromos = await db
      .select({
        id: promotions.id,
        itemGroupId: promotions.itemGroupId,
        itemGroupName: itemGroups.name,
        quantity: promotions.quantity,
        discountType: promotions.discountType,
        price: promotions.price,
        amountOff: promotions.amountOff,
        requiresLoyaltyId: promotions.requiresLoyaltyId,
        isActive: promotions.isActive,
        startDate: promotions.startDate,
        endDate: promotions.endDate,
      })
      .from(promotions)
      .leftJoin(itemGroups, eq(promotions.itemGroupId, itemGroups.id))
      .where(eq(promotions.isActive, true));

    const filteredPromos = [];
    
    for (const promo of activePromos) {
      if (promo.startDate && promo.startDate > now) continue;
      if (promo.endDate && promo.endDate < now) continue;

      const promoLocations = await db
        .select()
        .from(promotionLocations)
        .where(eq(promotionLocations.promotionId, promo.id));

      if (promoLocations.length === 0) {
        filteredPromos.push(promo);
      } else {
        const hasLocation = promoLocations.some(pl => pl.locationId === locationId);
        if (hasLocation) {
          filteredPromos.push(promo);
        }
      }
    }

    return filteredPromos;
  }

  async getPromotionById(id: number): Promise<Promotion | undefined> {
    const [promotion] = await db.select().from(promotions).where(eq(promotions.id, id));
    return promotion || undefined;
  }

  async createPromotion(insertPromotion: InsertPromotion): Promise<Promotion> {
    const [promotion] = await db
      .insert(promotions)
      .values(insertPromotion)
      .returning();
    return promotion;
  }

  async updatePromotion(id: number, updates: Partial<InsertPromotion>): Promise<Promotion | undefined> {
    const [updatedPromotion] = await db
      .update(promotions)
      .set(updates)
      .where(eq(promotions.id, id))
      .returning();
    return updatedPromotion || undefined;
  }

  async deletePromotion(id: number): Promise<void> {
    await db.delete(promotions).where(eq(promotions.id, id));
  }

  async searchPricebook(query: string): Promise<PricebookItem[]> {
    const results = await db
      .select()
      .from(pricebook)
      .where(
        or(
          ilike(pricebook.upc, `%${query}%`),
          ilike(pricebook.description, `%${query}%`)
        )
      )
      .limit(20);
    return results;
  }

  async createPricebookItem(item: { upc: string; description: string }): Promise<PricebookItem> {
    const [newItem] = await db
      .insert(pricebook)
      .values(item)
      .returning();
    return newItem;
  }

  async getPromotionLocations(promotionId: number): Promise<PromotionLocation[]> {
    const promoLocations = await db
      .select()
      .from(promotionLocations)
      .where(eq(promotionLocations.promotionId, promotionId));
    return promoLocations;
  }

  async addLocationToPromotion(insertPromoLocation: InsertPromotionLocation): Promise<PromotionLocation> {
    const [promoLocation] = await db
      .insert(promotionLocations)
      .values(insertPromoLocation)
      .returning();
    return promoLocation;
  }

  async deletePromotionLocation(id: number): Promise<void> {
    await db.delete(promotionLocations).where(eq(promotionLocations.id, id));
  }

  async deleteAllPromotionLocations(promotionId: number): Promise<void> {
    await db.delete(promotionLocations).where(eq(promotionLocations.promotionId, promotionId));
  }

  async upsertPosPresence(data: {
    pdiStoreNumber: string;
    posId?: string;
    posType: string;
    posIpAddress?: string;
    edgeIpAddress?: string;
    edgeVersion?: string;
  }): Promise<void> {
    const location = await db
      .select()
      .from(locations)
      .where(eq(locations.pdiStoreNumber, data.pdiStoreNumber))
      .limit(1);

    const existing = await db
      .select()
      .from(posPresence)
      .where(
        and(
          eq(posPresence.pdiStoreNumber, data.pdiStoreNumber),
          eq(posPresence.posType, data.posType)
        )
      )
      .limit(1);

    if (existing.length > 0) {
      await db
        .update(posPresence)
        .set({
          posId: data.posId,
          posIpAddress: data.posIpAddress,
          edgeIpAddress: data.edgeIpAddress,
          edgeVersion: data.edgeVersion,
          lastSeen: new Date(),
          status: 'online',
        })
        .where(eq(posPresence.id, existing[0].id));
    } else {
      await db.insert(posPresence).values({
        locationId: location[0]?.id || null,
        pdiStoreNumber: data.pdiStoreNumber,
        posId: data.posId || null,
        posType: data.posType,
        posIpAddress: data.posIpAddress || null,
        edgeIpAddress: data.edgeIpAddress || null,
        edgeVersion: data.edgeVersion || null,
        status: 'online',
        lastSeen: new Date(),
      });
    }
  }

  async getAllPosPresence(): Promise<any[]> {
    const presenceRecords = await db
      .select({
        id: posPresence.id,
        locationId: posPresence.locationId,
        locationName: locations.locationName,
        pdiStoreNumber: posPresence.pdiStoreNumber,
        posId: posPresence.posId,
        posType: posPresence.posType,
        posIpAddress: posPresence.posIpAddress,
        edgeIpAddress: posPresence.edgeIpAddress,
        edgeVersion: posPresence.edgeVersion,
        status: posPresence.status,
        lastSeen: posPresence.lastSeen,
      })
      .from(posPresence)
      .leftJoin(locations, eq(posPresence.locationId, locations.id))
      .orderBy(desc(posPresence.lastSeen));
    return presenceRecords;
  }

  // ============================================
  // SALES ANALYTICS STORAGE METHODS
  // ============================================

  async storeRawXml(data: InsertSalesRawXml): Promise<SalesRawXml> {
    const [record] = await db.insert(salesRawXml).values(data).returning();
    return record;
  }

  async getRawXmlById(id: number): Promise<SalesRawXml | undefined> {
    const [record] = await db.select().from(salesRawXml).where(eq(salesRawXml.id, id));
    return record || undefined;
  }

  async getRawXmlByFilters(filters: {
    pdiStoreNumber?: string;
    reportType?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
  }): Promise<SalesRawXml[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesRawXml.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.reportType) {
      conditions.push(eq(salesRawXml.reportType, filters.reportType));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesRawXml.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesRawXml.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesRawXml.businessDate} <= ${filters.endDate}`);
    }

    if (conditions.length > 0) {
      return db.select().from(salesRawXml).where(and(...conditions)).orderBy(desc(salesRawXml.uploadedAt));
    }
    
    return db.select().from(salesRawXml).orderBy(desc(salesRawXml.uploadedAt));
  }

  async updateRawXmlStatus(id: number, status: string, errorMessage: string | null): Promise<void> {
    await db
      .update(salesRawXml)
      .set({ 
        processingStatus: status,
        processedAt: status === 'processed' ? new Date() : null,
        errorMessage 
      })
      .where(eq(salesRawXml.id, id));
  }

  async bulkInsertTransactions(data: InsertSalesTransaction[]): Promise<void> {
    if (data.length === 0) return;
    await db.insert(salesTransactions).values(data);
  }

  async bulkInsertLineItems(data: InsertSalesLineItem[]): Promise<void> {
    if (data.length === 0) return;
    await db.insert(salesLineItems).values(data);
  }

  async deleteFuelGradesForDate(pdiStoreNumber: string, businessDate: string): Promise<void> {
    await db
      .delete(salesFuelGrades)
      .where(
        and(
          eq(salesFuelGrades.pdiStoreNumber, pdiStoreNumber),
          eq(salesFuelGrades.businessDate, businessDate)
        )
      );
  }

  async deleteItemsForDate(pdiStoreNumber: string, businessDate: string): Promise<void> {
    await db
      .delete(salesItems)
      .where(
        and(
          eq(salesItems.pdiStoreNumber, pdiStoreNumber),
          eq(salesItems.businessDate, businessDate)
        )
      );
  }

  async deleteDepartmentsForDate(pdiStoreNumber: string, businessDate: string): Promise<void> {
    await db
      .delete(salesDepartments)
      .where(
        and(
          eq(salesDepartments.pdiStoreNumber, pdiStoreNumber),
          eq(salesDepartments.businessDate, businessDate)
        )
      );
  }

  async deleteTransactionsForDate(pdiStoreNumber: string, businessDate: string): Promise<void> {
    await db
      .delete(salesTransactions)
      .where(
        and(
          eq(salesTransactions.pdiStoreNumber, pdiStoreNumber),
          eq(salesTransactions.businessDate, businessDate)
        )
      );
  }

  async deleteLineItemsForDate(pdiStoreNumber: string, businessDate: string): Promise<void> {
    await db
      .delete(salesLineItems)
      .where(
        and(
          eq(salesLineItems.pdiStoreNumber, pdiStoreNumber),
          eq(salesLineItems.businessDate, businessDate)
        )
      );
  }

  async deleteLoyaltyUsageForDate(pdiStoreNumber: string, businessDate: string): Promise<void> {
    await db
      .delete(salesLoyaltyUsage)
      .where(
        and(
          eq(salesLoyaltyUsage.pdiStoreNumber, pdiStoreNumber),
          eq(salesLoyaltyUsage.businessDate, businessDate)
        )
      );
  }

  async bulkInsertFuelGrades(data: InsertSalesFuelGrade[]): Promise<void> {
    if (data.length === 0) return;
    await db.insert(salesFuelGrades).values(data);
  }

  async bulkInsertItems(data: InsertSalesItem[]): Promise<void> {
    if (data.length === 0) return;
    await db.insert(salesItems).values(data);
  }

  async bulkInsertDepartments(data: InsertSalesDepartment[]): Promise<void> {
    if (data.length === 0) return;
    await db.insert(salesDepartments).values(data);
  }

  async bulkInsertLoyaltyUsage(data: InsertSalesLoyaltyUsage[]): Promise<void> {
    if (data.length === 0) return;
    await db.insert(salesLoyaltyUsage).values(data);
  }

  async getSalesTransactionsByFilters(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
    limit?: number;
    offset?: number;
  }): Promise<SalesTransaction[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesTransactions.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesTransactions.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesTransactions.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesTransactions.businessDate} <= ${filters.endDate}`);
    }

    const baseQuery = db
      .select()
      .from(salesTransactions)
      .where(conditions.length > 0 ? and(...conditions) : undefined)
      .orderBy(desc(salesTransactions.transactionDateTime))
      .$dynamic();

    if (filters.limit && filters.offset) {
      return baseQuery.limit(filters.limit).offset(filters.offset);
    } else if (filters.limit) {
      return baseQuery.limit(filters.limit);
    } else if (filters.offset) {
      return baseQuery.offset(filters.offset);
    }

    return baseQuery;
  }

  async getSalesFuelGradesByFilters(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
  }): Promise<SalesFuelGrade[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesFuelGrades.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesFuelGrades.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesFuelGrades.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesFuelGrades.businessDate} <= ${filters.endDate}`);
    }

    if (conditions.length > 0) {
      return db.select().from(salesFuelGrades).where(and(...conditions)).orderBy(desc(salesFuelGrades.businessDate));
    }
    
    return db.select().from(salesFuelGrades).orderBy(desc(salesFuelGrades.businessDate));
  }

  async getSalesItemsByFilters(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
    limit?: number;
  }): Promise<SalesItem[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesItems.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesItems.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesItems.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesItems.businessDate} <= ${filters.endDate}`);
    }

    const baseQuery = db
      .select()
      .from(salesItems)
      .where(conditions.length > 0 ? and(...conditions) : undefined)
      .orderBy(desc(salesItems.salesAmount))
      .$dynamic();

    if (filters.limit) {
      return baseQuery.limit(filters.limit);
    }

    return baseQuery;
  }

  async getSalesDepartmentsByFilters(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
  }): Promise<SalesDepartment[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesDepartments.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesDepartments.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesDepartments.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesDepartments.businessDate} <= ${filters.endDate}`);
    }

    if (conditions.length > 0) {
      return db.select().from(salesDepartments).where(and(...conditions)).orderBy(desc(salesDepartments.salesAmount));
    }
    
    return db.select().from(salesDepartments).orderBy(desc(salesDepartments.salesAmount));
  }

  async getSalesLineItemsByFilters(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
    limit?: number;
  }): Promise<SalesLineItem[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesLineItems.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesLineItems.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesLineItems.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesLineItems.businessDate} <= ${filters.endDate}`);
    }

    const baseQuery = db
      .select()
      .from(salesLineItems)
      .where(conditions.length > 0 ? and(...conditions) : undefined)
      .orderBy(desc(salesLineItems.amount))
      .$dynamic();

    if (filters.limit) {
      return baseQuery.limit(filters.limit);
    }
    
    return baseQuery;
  }

  async getLineItemsByTransaction(transactionId: string, businessDate: string): Promise<SalesLineItem[]> {
    return db
      .select()
      .from(salesLineItems)
      .where(
        and(
          eq(salesLineItems.posTransactionId, transactionId),
          eq(salesLineItems.businessDate, businessDate)
        )
      )
      .orderBy(salesLineItems.id);
  }

  async getSalesLoyaltyUsageByFilters(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
  }): Promise<SalesLoyaltyUsage[]> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesLoyaltyUsage.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesLoyaltyUsage.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesLoyaltyUsage.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesLoyaltyUsage.businessDate} <= ${filters.endDate}`);
    }

    if (conditions.length > 0) {
      return db.select().from(salesLoyaltyUsage).where(and(...conditions)).orderBy(desc(salesLoyaltyUsage.promotionAmount));
    }
    
    return db.select().from(salesLoyaltyUsage).orderBy(desc(salesLoyaltyUsage.promotionAmount));
  }

  async getSalesSummary(filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
  }): Promise<any> {
    const conditions = [];
    
    if (filters.pdiStoreNumber) {
      conditions.push(eq(salesTransactions.pdiStoreNumber, filters.pdiStoreNumber));
    }
    if (filters.businessDate) {
      conditions.push(eq(salesTransactions.businessDate, filters.businessDate));
    }
    if (filters.startDate) {
      conditions.push(sql`${salesTransactions.businessDate} >= ${filters.startDate}`);
    }
    if (filters.endDate) {
      conditions.push(sql`${salesTransactions.businessDate} <= ${filters.endDate}`);
    }

    const [summary] = await db
      .select({
        totalTransactions: sql<number>`COUNT(*)`,
        totalSales: sql<number>`SUM(${salesTransactions.totalAmount})`,
        totalFuelSales: sql<number>`SUM(${salesTransactions.fuelAmount})`,
        totalMerchSales: sql<number>`SUM(${salesTransactions.merchAmount})`,
        totalFuelVolume: sql<number>`SUM(${salesTransactions.fuelVolume})`,
      })
      .from(salesTransactions)
      .where(conditions.length > 0 ? and(...conditions) : undefined);

    return summary;
  }
}

export const storage = new DatabaseStorage();
