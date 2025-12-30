import { Router, Request, Response } from 'express';
import { db } from '../db';
import { 
  punchCardPromotions, 
  customerPunches, 
  punchCardHistory,
  itemGroups,
  itemGroupUpcs,
  users
} from '../../shared/schema';
import { eq, and, desc, gte, lte, sql, inArray } from 'drizzle-orm';

const router = Router();

// ============================================
// ADMIN ENDPOINTS - Manage Punch Card Promotions
// ============================================

router.get('/promotions', async (req: Request, res: Response) => {
  try {
    const promotions = await db
      .select({
        id: punchCardPromotions.id,
        name: punchCardPromotions.name,
        itemGroupId: punchCardPromotions.itemGroupId,
        itemGroupName: itemGroups.name,
        punchesRequired: punchCardPromotions.punchesRequired,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
        isActive: punchCardPromotions.isActive,
        startDate: punchCardPromotions.startDate,
        endDate: punchCardPromotions.endDate,
        createdAt: punchCardPromotions.createdAt,
      })
      .from(punchCardPromotions)
      .leftJoin(itemGroups, eq(punchCardPromotions.itemGroupId, itemGroups.id))
      .orderBy(desc(punchCardPromotions.createdAt));

    res.json(promotions);
  } catch (error) {
    console.log('Get punch card promotions error:', error);
    res.status(500).json({ error: 'Failed to get punch card promotions' });
  }
});

router.get('/promotions/:id', async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id);
    const [promotion] = await db
      .select({
        id: punchCardPromotions.id,
        name: punchCardPromotions.name,
        itemGroupId: punchCardPromotions.itemGroupId,
        itemGroupName: itemGroups.name,
        punchesRequired: punchCardPromotions.punchesRequired,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
        isActive: punchCardPromotions.isActive,
        startDate: punchCardPromotions.startDate,
        endDate: punchCardPromotions.endDate,
        createdAt: punchCardPromotions.createdAt,
      })
      .from(punchCardPromotions)
      .leftJoin(itemGroups, eq(punchCardPromotions.itemGroupId, itemGroups.id))
      .where(eq(punchCardPromotions.id, id));

    if (!promotion) {
      return res.status(404).json({ error: 'Punch card promotion not found' });
    }

    res.json(promotion);
  } catch (error) {
    console.log('Get punch card promotion error:', error);
    res.status(500).json({ error: 'Failed to get punch card promotion' });
  }
});

router.post('/promotions', async (req: Request, res: Response) => {
  try {
    const { name, itemGroupId, punchesRequired, rewardType, rewardValue, isActive, startDate, endDate } = req.body;

    if (!name || !itemGroupId) {
      return res.status(400).json({ error: 'Name and item group are required' });
    }

    const [promotion] = await db.insert(punchCardPromotions).values({
      name,
      itemGroupId,
      punchesRequired: punchesRequired || 10,
      rewardType: rewardType || 'free_item',
      rewardValue: rewardValue ? rewardValue.toString() : null,
      isActive: isActive !== undefined ? isActive : true,
      startDate: startDate ? new Date(startDate) : null,
      endDate: endDate ? new Date(endDate) : null,
    }).returning();

    res.status(201).json(promotion);
  } catch (error) {
    console.log('Create punch card promotion error:', error);
    res.status(500).json({ error: 'Failed to create punch card promotion' });
  }
});

router.put('/promotions/:id', async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id);
    const { name, itemGroupId, punchesRequired, rewardType, rewardValue, isActive, startDate, endDate } = req.body;

    const updates: any = { updatedAt: new Date() };
    if (name !== undefined) updates.name = name;
    if (itemGroupId !== undefined) updates.itemGroupId = itemGroupId;
    if (punchesRequired !== undefined) updates.punchesRequired = punchesRequired;
    if (rewardType !== undefined) updates.rewardType = rewardType;
    if (rewardValue !== undefined) updates.rewardValue = rewardValue ? rewardValue.toString() : null;
    if (isActive !== undefined) updates.isActive = isActive;
    if (startDate !== undefined) updates.startDate = startDate ? new Date(startDate) : null;
    if (endDate !== undefined) updates.endDate = endDate ? new Date(endDate) : null;

    const [updated] = await db
      .update(punchCardPromotions)
      .set(updates)
      .where(eq(punchCardPromotions.id, id))
      .returning();

    if (!updated) {
      return res.status(404).json({ error: 'Punch card promotion not found' });
    }

    res.json(updated);
  } catch (error) {
    console.log('Update punch card promotion error:', error);
    res.status(500).json({ error: 'Failed to update punch card promotion' });
  }
});

router.delete('/promotions/:id', async (req: Request, res: Response) => {
  try {
    const id = parseInt(req.params.id);
    await db.delete(punchCardPromotions).where(eq(punchCardPromotions.id, id));
    res.status(204).send();
  } catch (error) {
    console.log('Delete punch card promotion error:', error);
    res.status(500).json({ error: 'Failed to delete punch card promotion' });
  }
});

// ============================================
// POS ENDPOINTS - For Edge Agents
// ============================================

router.post('/record-purchase', async (req: Request, res: Response) => {
  try {
    const { customerId, lineItems, pdiStoreNumber, transactionId } = req.body;

    if (!customerId || !lineItems || !Array.isArray(lineItems)) {
      return res.status(400).json({ error: 'customerId and lineItems are required' });
    }

    console.log(`[PunchCard] Recording purchase for customer ${customerId}`);

    const activePunchCards = await db
      .select({
        id: punchCardPromotions.id,
        name: punchCardPromotions.name,
        itemGroupId: punchCardPromotions.itemGroupId,
        punchesRequired: punchCardPromotions.punchesRequired,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
      })
      .from(punchCardPromotions)
      .where(eq(punchCardPromotions.isActive, true));

    if (activePunchCards.length === 0) {
      return res.json({ message: 'No active punch cards', punchesRecorded: [] });
    }

    const punchCardItemGroups = await Promise.all(
      activePunchCards.map(async (pc) => {
        const upcs = await db
          .select({ upc: itemGroupUpcs.upc })
          .from(itemGroupUpcs)
          .where(eq(itemGroupUpcs.itemGroupId, pc.itemGroupId));
        return { ...pc, upcs: upcs.map(u => u.upc) };
      })
    );

    const punchesRecorded: any[] = [];

    for (const item of lineItems) {
      const upc = (item.upc || '').trim();
      const quantity = Math.floor(parseFloat(item.quantity || 1));
      const amount = parseFloat(item.amount || 0);

      // Skip free items (amount <= 0) - these are reward items, not paid purchases
      if (amount <= 0) {
        console.log(`[PunchCard] Skipping free item UPC ${upc} (amount: ${amount})`);
        continue;
      }

      for (const punchCard of punchCardItemGroups) {
        if (punchCard.upcs.includes(upc)) {
          let [customerPunch] = await db
            .select()
            .from(customerPunches)
            .where(and(
              eq(customerPunches.customerId, customerId),
              eq(customerPunches.punchCardId, punchCard.id)
            ));

          if (!customerPunch) {
            [customerPunch] = await db.insert(customerPunches).values({
              customerId,
              punchCardId: punchCard.id,
              currentPunches: 0,
              totalPunchesEarned: 0,
              totalRewardsRedeemed: 0,
            }).returning();
          }

          const punchesBefore = customerPunch.currentPunches;
          const newPunches = punchesBefore + quantity;
          const punchesRequired = punchCard.punchesRequired;

          await db.update(customerPunches)
            .set({
              currentPunches: newPunches,
              totalPunchesEarned: customerPunch.totalPunchesEarned + quantity,
              lastPunchDate: new Date(),
              updatedAt: new Date(),
            })
            .where(eq(customerPunches.id, customerPunch.id));

          await db.insert(punchCardHistory).values({
            customerId,
            punchCardId: punchCard.id,
            pdiStoreNumber: pdiStoreNumber || null,
            actionType: 'punch',
            punchesChanged: quantity,
            punchesBefore,
            punchesAfter: newPunches,
            upc,
            transactionId: transactionId || null,
          });

          punchesRecorded.push({
            punchCardId: punchCard.id,
            punchCardName: punchCard.name,
            upc,
            punchesAdded: quantity,
            currentPunches: newPunches,
            punchesRequired,
            rewardEarned: newPunches >= punchesRequired,
          });

          console.log(`[PunchCard] Customer ${customerId}: ${punchCard.name} - ${newPunches}/${punchesRequired} punches`);
        }
      }
    }

    res.json({
      success: true,
      punchesRecorded,
      message: punchesRecorded.length > 0 
        ? `Recorded ${punchesRecorded.length} punch(es)` 
        : 'No qualifying items for punch cards',
    });
  } catch (error) {
    console.log('Record punch error:', error);
    res.status(500).json({ error: 'Failed to record punch' });
  }
});

router.get('/customer/:customerId', async (req: Request, res: Response) => {
  try {
    const customerId = parseInt(req.params.customerId);

    // Get ALL active punch card promotions
    const allActiveCards = await db
      .select({
        punchCardId: punchCardPromotions.id,
        punchCardName: punchCardPromotions.name,
        itemGroupName: itemGroups.name,
        punchesRequired: punchCardPromotions.punchesRequired,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
      })
      .from(punchCardPromotions)
      .leftJoin(itemGroups, eq(punchCardPromotions.itemGroupId, itemGroups.id))
      .where(eq(punchCardPromotions.isActive, true));

    // Get customer's existing punch progress
    const customerProgress = await db
      .select({
        punchCardId: customerPunches.punchCardId,
        currentPunches: customerPunches.currentPunches,
        totalPunchesEarned: customerPunches.totalPunchesEarned,
        totalRewardsRedeemed: customerPunches.totalRewardsRedeemed,
        lastPunchDate: customerPunches.lastPunchDate,
        lastRewardDate: customerPunches.lastRewardDate,
      })
      .from(customerPunches)
      .where(eq(customerPunches.customerId, customerId));

    // Create a map for quick lookup
    const progressMap = new Map(customerProgress.map(p => [p.punchCardId, p]));

    // Merge: show all active cards with customer's progress (or 0 if not started)
    const punchCards = allActiveCards.map(card => {
      const progress = progressMap.get(card.punchCardId);
      const currentPunches = progress?.currentPunches || 0;
      const punchesRequired = card.punchesRequired || 10;
      
      return {
        punchCardId: card.punchCardId,
        punchCardName: card.punchCardName,
        itemGroupName: card.itemGroupName,
        currentPunches,
        punchesRequired,
        rewardType: card.rewardType,
        rewardValue: card.rewardValue,
        totalPunchesEarned: progress?.totalPunchesEarned || 0,
        totalRewardsRedeemed: progress?.totalRewardsRedeemed || 0,
        lastPunchDate: progress?.lastPunchDate || null,
        lastRewardDate: progress?.lastRewardDate || null,
        punchesRemaining: Math.max(0, punchesRequired - currentPunches),
        rewardReady: currentPunches >= punchesRequired,
      };
    });

    res.json(punchCards);
  } catch (error) {
    console.log('Get customer punches error:', error);
    res.status(500).json({ error: 'Failed to get customer punches' });
  }
});

router.post('/redeem', async (req: Request, res: Response) => {
  try {
    const { customerId, punchCardId, pdiStoreNumber, transactionId } = req.body;

    if (!customerId || !punchCardId) {
      return res.status(400).json({ error: 'customerId and punchCardId are required' });
    }

    const [punchCard] = await db
      .select()
      .from(punchCardPromotions)
      .where(eq(punchCardPromotions.id, punchCardId));

    if (!punchCard) {
      return res.status(404).json({ error: 'Punch card not found' });
    }

    const [customerPunch] = await db
      .select()
      .from(customerPunches)
      .where(and(
        eq(customerPunches.customerId, customerId),
        eq(customerPunches.punchCardId, punchCardId)
      ));

    if (!customerPunch) {
      return res.status(400).json({ error: 'Customer has no punches on this card' });
    }

    if (customerPunch.currentPunches < punchCard.punchesRequired) {
      return res.status(400).json({ 
        error: 'Not enough punches for reward',
        currentPunches: customerPunch.currentPunches,
        punchesRequired: punchCard.punchesRequired,
      });
    }

    const punchesBefore = customerPunch.currentPunches;
    const punchesAfter = punchesBefore - punchCard.punchesRequired;

    await db.update(customerPunches)
      .set({
        currentPunches: punchesAfter,
        totalRewardsRedeemed: customerPunch.totalRewardsRedeemed + 1,
        lastRewardDate: new Date(),
        updatedAt: new Date(),
      })
      .where(eq(customerPunches.id, customerPunch.id));

    await db.insert(punchCardHistory).values({
      customerId,
      punchCardId,
      pdiStoreNumber: pdiStoreNumber || null,
      actionType: 'redeem',
      punchesChanged: -punchCard.punchesRequired,
      punchesBefore,
      punchesAfter,
      transactionId: transactionId || null,
    });

    console.log(`[PunchCard] Customer ${customerId} redeemed reward on ${punchCard.name}`);

    res.json({
      success: true,
      rewardType: punchCard.rewardType,
      rewardValue: punchCard.rewardValue,
      punchesRedeemed: punchCard.punchesRequired,
      punchesRemaining: punchesAfter,
      message: `Reward redeemed! ${punchesAfter} punches remaining.`,
    });
  } catch (error) {
    console.log('Redeem reward error:', error);
    res.status(500).json({ error: 'Failed to redeem reward' });
  }
});

// ============================================
// REPORTING ENDPOINTS
// ============================================

router.get('/reports/activity', async (req: Request, res: Response) => {
  try {
    const { startDate, endDate, punchCardId } = req.query;

    const conditions: any[] = [];
    
    if (startDate) {
      conditions.push(gte(punchCardHistory.createdAt, new Date(startDate as string)));
    }
    if (endDate) {
      conditions.push(lte(punchCardHistory.createdAt, new Date(endDate as string)));
    }
    if (punchCardId) {
      conditions.push(eq(punchCardHistory.punchCardId, parseInt(punchCardId as string)));
    }

    const history = await db
      .select({
        id: punchCardHistory.id,
        customerId: punchCardHistory.customerId,
        customerName: users.firstName,
        punchCardId: punchCardHistory.punchCardId,
        punchCardName: punchCardPromotions.name,
        pdiStoreNumber: punchCardHistory.pdiStoreNumber,
        actionType: punchCardHistory.actionType,
        punchesChanged: punchCardHistory.punchesChanged,
        punchesBefore: punchCardHistory.punchesBefore,
        punchesAfter: punchCardHistory.punchesAfter,
        upc: punchCardHistory.upc,
        transactionId: punchCardHistory.transactionId,
        createdAt: punchCardHistory.createdAt,
      })
      .from(punchCardHistory)
      .leftJoin(punchCardPromotions, eq(punchCardHistory.punchCardId, punchCardPromotions.id))
      .leftJoin(users, eq(punchCardHistory.customerId, users.id))
      .where(conditions.length > 0 ? and(...conditions) : undefined)
      .orderBy(desc(punchCardHistory.createdAt))
      .limit(500);

    res.json(history);
  } catch (error) {
    console.log('Get punch card activity error:', error);
    res.status(500).json({ error: 'Failed to get punch card activity' });
  }
});

router.get('/reports/summary', async (req: Request, res: Response) => {
  try {
    const totalPunchCards = await db
      .select({ count: sql<number>`count(*)` })
      .from(punchCardPromotions);

    const activePunchCards = await db
      .select({ count: sql<number>`count(*)` })
      .from(punchCardPromotions)
      .where(eq(punchCardPromotions.isActive, true));

    const totalPunches = await db
      .select({ total: sql<number>`sum(${customerPunches.totalPunchesEarned})` })
      .from(customerPunches);

    const totalRedemptions = await db
      .select({ total: sql<number>`sum(${customerPunches.totalRewardsRedeemed})` })
      .from(customerPunches);

    const customersWithPunches = await db
      .select({ count: sql<number>`count(distinct ${customerPunches.customerId})` })
      .from(customerPunches);

    const closeToReward = await db
      .select({ count: sql<number>`count(*)` })
      .from(customerPunches)
      .leftJoin(punchCardPromotions, eq(customerPunches.punchCardId, punchCardPromotions.id))
      .where(sql`${customerPunches.currentPunches} >= ${punchCardPromotions.punchesRequired} - 2`);

    res.json({
      totalPunchCards: totalPunchCards[0]?.count || 0,
      activePunchCards: activePunchCards[0]?.count || 0,
      totalPunchesRecorded: totalPunches[0]?.total || 0,
      totalRewardsRedeemed: totalRedemptions[0]?.total || 0,
      customersWithPunches: customersWithPunches[0]?.count || 0,
      customersCloseToReward: closeToReward[0]?.count || 0,
    });
  } catch (error) {
    console.log('Get punch card summary error:', error);
    res.status(500).json({ error: 'Failed to get punch card summary' });
  }
});

// Get all customers with their punch progress
router.get('/reports/customers', async (req: Request, res: Response) => {
  try {
    const { punchCardId, search } = req.query;

    // Get all customer punch records with customer and punch card details
    let query = db
      .select({
        customerId: customerPunches.customerId,
        customerFirstName: users.firstName,
        customerLastName: users.lastName,
        customerPhone: users.phone,
        punchCardId: customerPunches.punchCardId,
        punchCardName: punchCardPromotions.name,
        itemGroupName: itemGroups.name,
        currentPunches: customerPunches.currentPunches,
        punchesRequired: punchCardPromotions.punchesRequired,
        totalPunchesEarned: customerPunches.totalPunchesEarned,
        totalRewardsRedeemed: customerPunches.totalRewardsRedeemed,
        lastPunchDate: customerPunches.lastPunchDate,
        lastRewardDate: customerPunches.lastRewardDate,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
      })
      .from(customerPunches)
      .leftJoin(users, eq(customerPunches.customerId, users.id))
      .leftJoin(punchCardPromotions, eq(customerPunches.punchCardId, punchCardPromotions.id))
      .leftJoin(itemGroups, eq(punchCardPromotions.itemGroupId, itemGroups.id))
      .orderBy(desc(customerPunches.lastPunchDate));

    const results = await query;

    // Filter by punchCardId if provided
    let filtered = results;
    if (punchCardId) {
      filtered = filtered.filter(r => r.punchCardId === parseInt(punchCardId as string));
    }

    // Filter by search term (customer name or phone)
    if (search) {
      const searchLower = (search as string).toLowerCase();
      filtered = filtered.filter(r => 
        (r.customerFirstName?.toLowerCase() || '').includes(searchLower) ||
        (r.customerLastName?.toLowerCase() || '').includes(searchLower) ||
        (r.customerPhone || '').includes(searchLower)
      );
    }

    // Enrich with computed fields
    const enriched = filtered.map(r => ({
      ...r,
      customerName: `${r.customerFirstName || ''} ${r.customerLastName || ''}`.trim() || 'Unknown',
      punchesRemaining: Math.max(0, (r.punchesRequired || 10) - (r.currentPunches || 0)),
      rewardReady: (r.currentPunches || 0) >= (r.punchesRequired || 10),
      progressPercent: Math.min(100, Math.round(((r.currentPunches || 0) / (r.punchesRequired || 10)) * 100)),
    }));

    res.json(enriched);
  } catch (error) {
    console.log('Get customer punches report error:', error);
    res.status(500).json({ error: 'Failed to get customer punches report' });
  }
});

// Check punch status with projected punches for real-time reward evaluation
router.post('/evaluate', async (req: Request, res: Response) => {
  try {
    const { customerId, lineItems } = req.body;

    if (!customerId) {
      return res.status(400).json({ error: 'customerId is required' });
    }

    console.log(`[PunchCard] Evaluating for customer ${customerId} with ${lineItems?.length || 0} items`);
    
    // Debug: log the line items
    if (lineItems && lineItems.length > 0) {
      console.log(`[PunchCard] Line items UPCs: ${lineItems.map((i: any) => i.upc).join(', ')}`);
    }

    // Get current punch status (may be empty for first-time customers)
    const currentPunches = await db
      .select({
        id: customerPunches.id,
        punchCardId: customerPunches.punchCardId,
        punchCardName: punchCardPromotions.name,
        currentPunches: customerPunches.currentPunches,
        punchesRequired: punchCardPromotions.punchesRequired,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
        itemGroupId: punchCardPromotions.itemGroupId,
      })
      .from(customerPunches)
      .leftJoin(punchCardPromotions, eq(customerPunches.punchCardId, punchCardPromotions.id))
      .where(and(
        eq(customerPunches.customerId, customerId),
        eq(punchCardPromotions.isActive, true)
      ));

    // Get all active punch cards (for new customers who don't have punch records yet)
    const activePunchCards = await db
      .select({
        id: punchCardPromotions.id,
        name: punchCardPromotions.name,
        punchesRequired: punchCardPromotions.punchesRequired,
        rewardType: punchCardPromotions.rewardType,
        rewardValue: punchCardPromotions.rewardValue,
        itemGroupId: punchCardPromotions.itemGroupId,
      })
      .from(punchCardPromotions)
      .where(eq(punchCardPromotions.isActive, true));

    // Get UPCs for each punch card
    const punchCardUPCs: Record<number, string[]> = {};
    for (const pc of activePunchCards) {
      const upcs = await db
        .select({ upc: itemGroupUpcs.upc })
        .from(itemGroupUpcs)
        .where(eq(itemGroupUpcs.itemGroupId, pc.itemGroupId));
      punchCardUPCs[pc.id] = upcs.map(u => u.upc);
    }

    // Calculate projected punches from current basket
    const projectedPunches: any[] = [];
    
    for (const pc of activePunchCards) {
      const upcs = punchCardUPCs[pc.id] || [];
      let punchesFromBasket = 0;
      
      if (lineItems && Array.isArray(lineItems)) {
        for (const item of lineItems) {
          const upc = (item.upc || '').trim();
          const quantity = Math.floor(parseFloat(item.quantity || 1));
          const amount = parseFloat(item.amount || 0);
          
          // Only count paid items (amount > 0), skip free/reward items
          if (upcs.includes(upc) && amount > 0) {
            punchesFromBasket += quantity;
          }
        }
      }

      // Find current punch record or default to 0
      const existing = currentPunches.find(cp => cp.punchCardId === pc.id);
      const currentCount = existing?.currentPunches || 0;
      const projectedTotal = currentCount + punchesFromBasket;
      const punchesRequired = pc.punchesRequired || 10;

      // Check if reward should trigger with projected punches
      const rewardReady = projectedTotal >= punchesRequired;

      projectedPunches.push({
        punchCardId: pc.id,
        punchCardName: pc.name,
        currentPunches: currentCount,
        punchesFromBasket,
        projectedTotal,
        punchesRequired,
        rewardReady,
        rewardType: pc.rewardType,
        rewardValue: pc.rewardValue,
        punchesRemaining: Math.max(0, punchesRequired - projectedTotal),
      });

      // Log all evaluations for debugging
      console.log(`[PunchCard] ${pc.name}: ${currentCount} stored + ${punchesFromBasket} basket = ${projectedTotal}/${punchesRequired} ${rewardReady ? '🎁 REWARD!' : ''}`);
    }

    res.json({
      customerId,
      punchCards: projectedPunches,
      rewardsReady: projectedPunches.filter(p => p.rewardReady),
    });
  } catch (error) {
    console.log('Evaluate punch status error:', error);
    res.status(500).json({ error: 'Failed to evaluate punch status' });
  }
});

export default router;
