import { Router, Request, Response } from 'express';
import { db } from '../db.js';
import { loyaltyTransactions, loyaltyFailedLookups, users } from '../../shared/schema.js';
import { eq, and, gte, lte, desc, sql } from 'drizzle-orm';

const router = Router();

router.get('/reports/transactions', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!startDate) {
      return res.status(400).json({ error: 'startDate is required' });
    }

    const start = new Date(startDate as string);
    start.setHours(0, 0, 0, 0);
    
    const end = endDate ? new Date(endDate as string) : new Date(startDate as string);
    end.setHours(23, 59, 59, 999);

    let conditions = [
      gte(loyaltyTransactions.transactionDate, start),
      lte(loyaltyTransactions.transactionDate, end)
    ];

    if (storeNumber) {
      conditions.push(eq(loyaltyTransactions.pdiStoreNumber, storeNumber as string));
    }

    const transactions = await db
      .select()
      .from(loyaltyTransactions)
      .where(and(...conditions))
      .orderBy(desc(loyaltyTransactions.transactionDate))
      .limit(500);

    res.json(transactions);
  } catch (error) {
    console.error('Error fetching loyalty transactions:', error);
    res.status(500).json({ error: 'Failed to fetch transactions' });
  }
});

router.get('/reports/failed-lookups', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!startDate) {
      return res.status(400).json({ error: 'startDate is required' });
    }

    const start = new Date(startDate as string);
    start.setHours(0, 0, 0, 0);
    
    const end = endDate ? new Date(endDate as string) : new Date(startDate as string);
    end.setHours(23, 59, 59, 999);

    let conditions = [
      gte(loyaltyFailedLookups.lookupDate, start),
      lte(loyaltyFailedLookups.lookupDate, end)
    ];

    if (storeNumber) {
      conditions.push(eq(loyaltyFailedLookups.pdiStoreNumber, storeNumber as string));
    }

    const lookups = await db
      .select()
      .from(loyaltyFailedLookups)
      .where(and(...conditions))
      .orderBy(desc(loyaltyFailedLookups.lookupDate))
      .limit(500);

    res.json(lookups);
  } catch (error) {
    console.error('Error fetching failed lookups:', error);
    res.status(500).json({ error: 'Failed to fetch failed lookups' });
  }
});

router.get('/reports/promotion-usage', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!startDate) {
      return res.status(400).json({ error: 'startDate is required' });
    }

    const start = new Date(startDate as string);
    start.setHours(0, 0, 0, 0);
    
    const end = endDate ? new Date(endDate as string) : new Date(startDate as string);
    end.setHours(23, 59, 59, 999);

    let conditions = [
      gte(loyaltyTransactions.transactionDate, start),
      lte(loyaltyTransactions.transactionDate, end),
      eq(loyaltyTransactions.promotionUsed, true)
    ];

    if (storeNumber) {
      conditions.push(eq(loyaltyTransactions.pdiStoreNumber, storeNumber as string));
    }

    const promoTransactions = await db
      .select({
        date: sql<string>`DATE(${loyaltyTransactions.transactionDate})`.as('date'),
        storeNumber: loyaltyTransactions.pdiStoreNumber,
        promotionNames: loyaltyTransactions.promotionNames,
        promotionDiscount: loyaltyTransactions.promotionDiscount,
      })
      .from(loyaltyTransactions)
      .where(and(...conditions))
      .orderBy(desc(loyaltyTransactions.transactionDate));

    const promoMap = new Map<string, { 
      date: string; 
      storeNumber: string; 
      promotionName: string; 
      timesUsed: number; 
      totalDiscount: number;
    }>();

    for (const t of promoTransactions) {
      const promoNames = t.promotionNames?.split(',').map(s => s.trim()) || ['Unknown Promotion'];
      const discount = parseFloat(t.promotionDiscount?.toString() || '0');
      
      for (const promoName of promoNames) {
        const key = `${t.date}-${t.storeNumber}-${promoName}`;
        const existing = promoMap.get(key);
        
        if (existing) {
          existing.timesUsed++;
          existing.totalDiscount += discount / promoNames.length;
        } else {
          promoMap.set(key, {
            date: t.date,
            storeNumber: t.storeNumber,
            promotionName: promoName,
            timesUsed: 1,
            totalDiscount: discount / promoNames.length,
          });
        }
      }
    }

    const result = Array.from(promoMap.values()).map(p => ({
      ...p,
      avgDiscount: p.totalDiscount / p.timesUsed,
    }));

    res.json(result);
  } catch (error) {
    console.error('Error fetching promotion usage:', error);
    res.status(500).json({ error: 'Failed to fetch promotion usage' });
  }
});

router.get('/reports/points-activity', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!startDate) {
      return res.status(400).json({ error: 'startDate is required' });
    }

    const start = new Date(startDate as string);
    start.setHours(0, 0, 0, 0);
    
    const end = endDate ? new Date(endDate as string) : new Date(startDate as string);
    end.setHours(23, 59, 59, 999);

    let storeCondition = '';
    if (storeNumber) {
      storeCondition = `AND pdi_store_number = '${storeNumber}'`;
    }

    const result = await db.execute(sql`
      SELECT 
        DATE(transaction_date) as date,
        pdi_store_number as "storeNumber",
        SUM(points_earned) as "pointsEarned",
        SUM(points_redeemed) as "pointsRedeemed",
        SUM(points_earned) - SUM(points_redeemed) as "netPoints",
        SUM(points_discount) as "redemptionValue"
      FROM loyalty_transactions
      WHERE transaction_date >= ${start}
        AND transaction_date <= ${end}
        ${storeNumber ? sql`AND pdi_store_number = ${storeNumber}` : sql``}
      GROUP BY DATE(transaction_date), pdi_store_number
      ORDER BY date DESC, pdi_store_number
    `);

    res.json(result.rows);
  } catch (error) {
    console.error('Error fetching points activity:', error);
    res.status(500).json({ error: 'Failed to fetch points activity' });
  }
});

router.get('/reports/customer-activity', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!startDate) {
      return res.status(400).json({ error: 'startDate is required' });
    }

    const start = new Date(startDate as string);
    start.setHours(0, 0, 0, 0);
    
    const end = endDate ? new Date(endDate as string) : new Date(startDate as string);
    end.setHours(23, 59, 59, 999);

    const result = await db.execute(sql`
      SELECT 
        customer_id as "customerId",
        customer_name as "customerName",
        COUNT(*) as "totalVisits",
        SUM(net_amount) as "totalSpent",
        SUM(points_earned) as "pointsEarned",
        SUM(points_redeemed) as "pointsRedeemed",
        MAX(transaction_date) as "lastVisit"
      FROM loyalty_transactions
      WHERE transaction_date >= ${start}
        AND transaction_date <= ${end}
        ${storeNumber ? sql`AND pdi_store_number = ${storeNumber}` : sql``}
      GROUP BY customer_id, customer_name
      ORDER BY "totalSpent" DESC
      LIMIT 50
    `);

    res.json(result.rows);
  } catch (error) {
    console.error('Error fetching customer activity:', error);
    res.status(500).json({ error: 'Failed to fetch customer activity' });
  }
});

router.get('/reports/anomaly-alerts', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!startDate) {
      return res.status(400).json({ error: 'startDate is required' });
    }

    const start = new Date(startDate as string);
    start.setHours(0, 0, 0, 0);
    
    const end = endDate ? new Date(endDate as string) : new Date(startDate as string);
    end.setHours(23, 59, 59, 999);

    const bigSpenderThreshold = 100;

    const bigSpenders = await db.execute(sql`
      SELECT 
        transaction_date as "transactionDate",
        pdi_store_number as "storeNumber",
        customer_name as "customerName",
        net_amount as "amount",
        'Amount > $100' as "flagReason"
      FROM loyalty_transactions
      WHERE transaction_date >= ${start}
        AND transaction_date <= ${end}
        AND net_amount > ${bigSpenderThreshold}
        ${storeNumber ? sql`AND pdi_store_number = ${storeNumber}` : sql``}
      ORDER BY net_amount DESC
      LIMIT 50
    `);

    const frequentVisitors = await db.execute(sql`
      SELECT 
        customer_name as "customerName",
        pdi_store_number as "storeNumber",
        DATE(transaction_date) as "transactionDate",
        COUNT(*) as visit_count,
        SUM(net_amount) as "amount"
      FROM loyalty_transactions
      WHERE transaction_date >= ${start}
        AND transaction_date <= ${end}
        ${storeNumber ? sql`AND pdi_store_number = ${storeNumber}` : sql``}
      GROUP BY customer_name, pdi_store_number, DATE(transaction_date)
      HAVING COUNT(*) >= 5
      ORDER BY visit_count DESC
      LIMIT 50
    `);

    const frequentAlerts = (frequentVisitors.rows as any[]).map(r => ({
      ...r,
      flagReason: `${r.visit_count}+ transactions in one day`
    }));

    const allAlerts = [
      ...(bigSpenders.rows as any[]),
      ...frequentAlerts
    ].sort((a, b) => new Date(b.transactionDate).getTime() - new Date(a.transactionDate).getTime());

    res.json(allAlerts);
  } catch (error) {
    console.error('Error fetching anomaly alerts:', error);
    res.status(500).json({ error: 'Failed to fetch anomaly alerts' });
  }
});

router.get('/customer/:customerId/transactions', async (req: Request, res: Response) => {
  try {
    const customerId = parseInt(req.params.customerId);
    
    if (isNaN(customerId)) {
      return res.status(400).json({ error: 'Invalid customer ID' });
    }

    const transactions = await db
      .select()
      .from(loyaltyTransactions)
      .where(eq(loyaltyTransactions.customerId, customerId))
      .orderBy(desc(loyaltyTransactions.transactionDate))
      .limit(100);

    const formattedTransactions = transactions.map(t => ({
      id: t.id,
      transactionId: t.transactionId,
      transactionDate: t.transactionDate,
      pdiStoreNumber: t.pdiStoreNumber,
      subtotal: parseFloat(t.subtotal),
      promotionDiscount: parseFloat(t.promotionDiscount || '0'),
      pointsDiscount: parseFloat(t.pointsDiscount || '0'),
      totalDiscount: parseFloat(t.totalDiscount || '0'),
      netAmount: parseFloat(t.netAmount),
      pointsBefore: t.pointsBefore,
      pointsEarned: t.pointsEarned,
      pointsRedeemed: t.pointsRedeemed,
      pointsAfter: t.pointsAfter,
      promotionUsed: t.promotionUsed,
      promotionCount: t.promotionCount,
      promotionNames: t.promotionNames,
      promotionDetails: t.promotionDetails ? JSON.parse(t.promotionDetails) : null,
      lineItems: t.lineItems ? JSON.parse(t.lineItems) : [],
      itemCount: t.itemCount
    }));

    res.json(formattedTransactions);
  } catch (error) {
    console.error('Error fetching customer loyalty transactions:', error);
    res.status(500).json({ error: 'Failed to fetch customer transactions' });
  }
});

export default router;
