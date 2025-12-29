import { Router } from 'express';
import { storage } from '../storage';
import type { Request, Response } from 'express';
import { parseFGM, parseISM, parseMCM, parseCPJR } from '../xmlParsers';
import { getDepartmentForCategory } from '../departmentMapping';
import { parseVerifoneDepartmentsFromCPJR, aggregateByDepartment } from '../verifoneDepartmentParser';
import { parseVerifoneFuelGradesFromCPJR } from '../verifoneFuelGradeParser';
import { 
  generateVerifoneFullDayReport, 
  parseVerifoneTransactionJournal,
  parseVerifoneFGMCumulative,
  calculateDailyFuelFromCumulativeReadings
} from '../finalVerifoneParser';

const router = Router();

function parseFilters(req: Request): {
  pdiStoreNumber?: string;
  businessDate?: string;
  startDate?: string;
  endDate?: string;
  aggregate?: boolean;
} {
  const { pdiStoreNumber, businessDate, startDate, endDate, aggregate } = req.query;

  const filters: {
    pdiStoreNumber?: string;
    businessDate?: string;
    startDate?: string;
    endDate?: string;
    aggregate?: boolean;
  } = {};

  if (pdiStoreNumber && typeof pdiStoreNumber === 'string' && !pdiStoreNumber.includes(',')) {
    filters.pdiStoreNumber = pdiStoreNumber;
  }

  if (businessDate && typeof businessDate === 'string') {
    filters.businessDate = businessDate;
  } else if (startDate && typeof startDate === 'string' && endDate && typeof endDate === 'string') {
    filters.startDate = startDate;
    filters.endDate = endDate;
  } else if (startDate && typeof startDate === 'string') {
    filters.startDate = startDate;
    filters.endDate = startDate;
  }

  filters.aggregate = aggregate === 'true';

  return filters;
}

function getDatesInRange(startDate: string, endDate: string): string[] {
  const dates: string[] = [];
  const start = new Date(startDate);
  const end = new Date(endDate);
  
  const current = new Date(start);
  while (current <= end) {
    dates.push(current.toISOString().split('T')[0]);
    current.setDate(current.getDate() + 1);
  }
  
  return dates;
}

async function aggregateDataAcrossStores<T>(
  storeNumbers: string[],
  filters: any,
  fetchFn: (filters: any) => Promise<T[]>
): Promise<T[]> {
  if (storeNumbers.length === 0) {
    return fetchFn(filters);
  }

  const allResults = await Promise.all(
    storeNumbers.map(store => fetchFn({ ...filters, pdiStoreNumber: store }))
  );

  return allResults.flat();
}

// ============================================
// RAW XML UPLOAD ENDPOINT
// ============================================

router.post('/raw-xml/upload', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, reportType, businessDate, fileName, xmlContent } = req.body;

    if (!pdiStoreNumber || !reportType || !businessDate || !fileName || !xmlContent) {
      return res.status(400).json({ 
        error: 'Missing required fields: pdiStoreNumber, reportType, businessDate, fileName, xmlContent' 
      });
    }

    const location = await storage.getLocationByPdiStoreNumber(pdiStoreNumber);
    
    const record = await storage.storeRawXml({
      locationId: location?.id || null,
      pdiStoreNumber,
      reportType,
      businessDate,
      fileName,
      xmlContent,
      fileSize: xmlContent.length,
      processingStatus: 'pending',
    });

    res.status(201).json({ 
      success: true, 
      id: record.id,
      message: 'Raw XML stored successfully' 
    });
  } catch (error) {
    console.error('Raw XML upload error:', error);
    res.status(500).json({ error: 'Failed to store raw XML' });
  }
});

router.get('/raw-xml', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, reportType, businessDate, startDate, endDate } = req.query;

    const records = await storage.getRawXmlByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      reportType: reportType as string,
      businessDate: businessDate as string,
      startDate: startDate as string,
      endDate: endDate as string,
    });

    res.json(records);
  } catch (error) {
    console.error('Get raw XML error:', error);
    res.status(500).json({ error: 'Failed to retrieve raw XML' });
  }
});

router.post('/process-xml', async (req: Request, res: Response) => {
  try {
    const { businessDate } = req.body;

    if (!businessDate) {
      return res.status(400).json({ error: 'businessDate is required' });
    }

    const rawXmlRecords = await storage.getRawXmlByFilters({
      businessDate,
    });

    const pendingRecords = rawXmlRecords.filter(r => r.processingStatus === 'pending');

    if (pendingRecords.length === 0) {
      return res.json({ 
        success: true, 
        message: 'No pending XML files to process',
        processed: 0
      });
    }

    let processedCount = 0;
    let errorCount = 0;
    const errors: Array<{ fileName: string; error: string }> = [];

    for (const record of pendingRecords) {
      try {
        const location = await storage.getLocationByPdiStoreNumber(record.pdiStoreNumber);
        const locationId = location?.id || null;

        if (record.reportType === 'FGM') {
          const fuelGrades = await parseFGM(record.xmlContent, record.businessDate);
          
          await storage.deleteFuelGradesForDate(record.pdiStoreNumber, record.businessDate);
          
          const fuelGradeRecords = fuelGrades.map(fg => ({
            locationId,
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            gradeId: fg.gradeId,
            gradeName: fg.gradeName,
            volume: fg.volume.toString(),
            amount: fg.amount.toString(),
            discountAmount: fg.discountAmount.toString(),
          }));

          if (fuelGradeRecords.length > 0) {
            await storage.bulkInsertFuelGrades(fuelGradeRecords);
          }
        } else if (record.reportType === 'ISM') {
          const { items, departments } = await parseISM(record.xmlContent, record.businessDate);
          
          await storage.deleteItemsForDate(record.pdiStoreNumber, record.businessDate);
          await storage.deleteDepartmentsForDate(record.pdiStoreNumber, record.businessDate);
          
          const itemRecords = items.map(item => ({
            locationId,
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            upc: item.upc,
            description: item.description,
            quantity: item.quantity.toString(),
            salesAmount: item.salesAmount.toString(),
          }));

          const deptRecords = departments.map(dept => ({
            locationId,
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            departmentCode: dept.departmentCode,
            departmentName: dept.departmentName,
            salesAmount: dept.salesAmount.toString(),
            quantity: dept.quantity.toString(),
            transactionCount: dept.transactionCount,
          }));

          if (itemRecords.length > 0) {
            await storage.bulkInsertItems(itemRecords);
          }
          if (deptRecords.length > 0) {
            await storage.bulkInsertDepartments(deptRecords);
          }
        } else if (record.reportType === 'MCM') {
          const ismFiles = await storage.getRawXmlByFilters({
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            reportType: 'ISM',
          });

          if (ismFiles.length === 0) {
            await storage.deleteDepartmentsForDate(record.pdiStoreNumber, record.businessDate);
            
            const departments = await parseMCM(record.xmlContent, record.businessDate);
            
            const deptRecords = departments.map(dept => ({
              locationId,
              pdiStoreNumber: record.pdiStoreNumber,
              businessDate: record.businessDate,
              departmentCode: dept.departmentCode,
              departmentName: dept.departmentName,
              salesAmount: dept.salesAmount.toString(),
              quantity: dept.quantity.toString(),
              transactionCount: dept.transactionCount,
            }));

            if (deptRecords.length > 0) {
              await storage.bulkInsertDepartments(deptRecords);
            }
          }
        } else if (record.reportType === 'CPJR') {
          const cpjrData = await parseCPJR(record.xmlContent, record.businessDate);
          
          await storage.deleteTransactionsForDate(record.pdiStoreNumber, record.businessDate);
          await storage.deleteLineItemsForDate(record.pdiStoreNumber, record.businessDate);
          await storage.deleteLoyaltyUsageForDate(record.pdiStoreNumber, record.businessDate);
          
          const transactionRecords = cpjrData.transactions.map(tx => ({
            locationId,
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            transactionId: tx.transactionId,
            transactionDateTime: new Date(tx.transactionDateTime),
            cashierId: tx.cashierId,
            fuelVolume: tx.fuelVolume.toString(),
            fuelAmount: tx.fuelAmount.toString(),
            merchAmount: tx.merchAmount.toString(),
            totalAmount: tx.totalAmount.toString(),
            tenderType: tx.tenderType,
          }));

          const lineItemRecords = cpjrData.lineItems.map(item => ({
            locationId,
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            posTransactionId: item.posTransactionId,
            itemType: item.itemType,
            upc: item.upc,
            description: item.description,
            pumpNumber: item.pumpNumber,
            quantity: item.quantity.toString(),
            amount: item.amount.toString(),
          }));

          const loyaltyRecords = cpjrData.loyalty.map(loy => ({
            locationId,
            pdiStoreNumber: record.pdiStoreNumber,
            businessDate: record.businessDate,
            posTransactionId: loy.posTransactionId,
            promotionId: loy.promotionId,
            promotionAmount: loy.promotionAmount.toString(),
          }));

          if (transactionRecords.length > 0) {
            await storage.bulkInsertTransactions(transactionRecords);
          }
          if (lineItemRecords.length > 0) {
            await storage.bulkInsertLineItems(lineItemRecords);
          }
          if (loyaltyRecords.length > 0) {
            await storage.bulkInsertLoyaltyUsage(loyaltyRecords);
          }
        }

        await storage.updateRawXmlStatus(record.id, 'processed', null);
        processedCount++;
      } catch (error) {
        console.error(`Error processing ${record.fileName}:`, error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        await storage.updateRawXmlStatus(record.id, 'error', errorMessage);
        errorCount++;
        errors.push({ fileName: record.fileName, error: errorMessage });
      }
    }

    res.json({
      success: true,
      processed: processedCount,
      errors: errorCount,
      errorDetails: errors.length > 0 ? errors : undefined,
      message: `Processed ${processedCount} files successfully${errorCount > 0 ? `, ${errorCount} files had errors` : ''}`,
    });
  } catch (error) {
    console.error('Process XML error:', error);
    res.status(500).json({ error: 'Failed to process XML files' });
  }
});

// ============================================
// BATCH DATA INGESTION ENDPOINTS
// ============================================

router.post('/transactions/batch', async (req: Request, res: Response) => {
  try {
    const { transactions } = req.body;

    if (!Array.isArray(transactions)) {
      return res.status(400).json({ error: 'transactions must be an array' });
    }

    const records = await Promise.all(
      transactions.map(async (tx) => {
        const location = await storage.getLocationByPdiStoreNumber(tx.pdiStoreNumber);
        return {
          locationId: location?.id || null,
          pdiStoreNumber: tx.pdiStoreNumber,
          businessDate: tx.businessDate,
          transactionId: tx.transactionId,
          transactionDateTime: new Date(tx.transactionDateTime),
          cashierId: tx.cashierId || null,
          fuelVolume: tx.fuelVolume?.toString() || '0',
          fuelAmount: tx.fuelAmount?.toString() || '0',
          merchAmount: tx.merchAmount?.toString() || '0',
          totalAmount: tx.totalAmount?.toString() || '0',
          tenderType: tx.tenderType || null,
        };
      })
    );

    await storage.bulkInsertTransactions(records);

    res.status(201).json({ 
      success: true, 
      count: records.length,
      message: 'Transactions inserted successfully' 
    });
  } catch (error) {
    console.error('Batch transaction insert error:', error);
    res.status(500).json({ error: 'Failed to insert transactions' });
  }
});

router.post('/fuel-grades/batch', async (req: Request, res: Response) => {
  try {
    const { fuelGrades } = req.body;

    if (!Array.isArray(fuelGrades)) {
      return res.status(400).json({ error: 'fuelGrades must be an array' });
    }

    const records = await Promise.all(
      fuelGrades.map(async (fg) => {
        const location = await storage.getLocationByPdiStoreNumber(fg.pdiStoreNumber);
        return {
          locationId: location?.id || null,
          pdiStoreNumber: fg.pdiStoreNumber,
          businessDate: fg.businessDate,
          gradeId: fg.gradeId,
          gradeName: fg.gradeName || null,
          volume: fg.volume?.toString() || '0',
          amount: fg.amount?.toString() || '0',
          discountAmount: fg.discountAmount?.toString() || '0',
        };
      })
    );

    await storage.bulkInsertFuelGrades(records);

    res.status(201).json({ 
      success: true, 
      count: records.length,
      message: 'Fuel grades inserted successfully' 
    });
  } catch (error) {
    console.error('Batch fuel grade insert error:', error);
    res.status(500).json({ error: 'Failed to insert fuel grades' });
  }
});

router.post('/items/batch', async (req: Request, res: Response) => {
  try {
    const { items } = req.body;

    if (!Array.isArray(items)) {
      return res.status(400).json({ error: 'items must be an array' });
    }

    const records = await Promise.all(
      items.map(async (item) => {
        const location = await storage.getLocationByPdiStoreNumber(item.pdiStoreNumber);
        return {
          locationId: location?.id || null,
          pdiStoreNumber: item.pdiStoreNumber,
          businessDate: item.businessDate,
          upc: item.upc,
          description: item.description || null,
          quantity: item.quantity?.toString() || '0',
          salesAmount: item.salesAmount?.toString() || '0',
        };
      })
    );

    await storage.bulkInsertItems(records);

    res.status(201).json({ 
      success: true, 
      count: records.length,
      message: 'Items inserted successfully' 
    });
  } catch (error) {
    console.error('Batch item insert error:', error);
    res.status(500).json({ error: 'Failed to insert items' });
  }
});

router.post('/departments/batch', async (req: Request, res: Response) => {
  try {
    const { departments } = req.body;

    if (!Array.isArray(departments)) {
      return res.status(400).json({ error: 'departments must be an array' });
    }

    const records = await Promise.all(
      departments.map(async (dept) => {
        const location = await storage.getLocationByPdiStoreNumber(dept.pdiStoreNumber);
        return {
          locationId: location?.id || null,
          pdiStoreNumber: dept.pdiStoreNumber,
          businessDate: dept.businessDate,
          departmentCode: dept.departmentCode,
          departmentName: dept.departmentName || null,
          salesAmount: dept.salesAmount?.toString() || '0',
          quantity: dept.quantity?.toString() || '0',
          transactionCount: dept.transactionCount || 0,
        };
      })
    );

    await storage.bulkInsertDepartments(records);

    res.status(201).json({ 
      success: true, 
      count: records.length,
      message: 'Departments inserted successfully' 
    });
  } catch (error) {
    console.error('Batch department insert error:', error);
    res.status(500).json({ error: 'Failed to insert departments' });
  }
});

// ============================================
// DATA QUERY ENDPOINTS WITH FILTERS
// ============================================

router.get('/transactions', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate, startDate, endDate, limit, offset } = req.query;

    const transactions = await storage.getSalesTransactionsByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      startDate: startDate as string,
      endDate: endDate as string,
      limit: limit ? parseInt(limit as string) : undefined,
      offset: offset ? parseInt(offset as string) : undefined,
    });

    res.json(transactions);
  } catch (error) {
    console.error('Get transactions error:', error);
    res.status(500).json({ error: 'Failed to retrieve transactions' });
  }
});

router.get('/transaction-details', async (req: Request, res: Response) => {
  try {
    const { transactionId, businessDate } = req.query;

    if (!transactionId || !businessDate) {
      return res.status(400).json({ error: 'transactionId and businessDate are required' });
    }

    const lineItems = await storage.getLineItemsByTransaction(
      transactionId as string,
      businessDate as string
    );

    res.json({
      transactionId,
      businessDate,
      lineItems
    });
  } catch (error) {
    console.error('Get transaction details error:', error);
    res.status(500).json({ error: 'Failed to retrieve transaction details' });
  }
});

router.get('/fuel-grades', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate, startDate, endDate } = req.query;

    const fuelGrades = await storage.getSalesFuelGradesByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      startDate: startDate as string,
      endDate: endDate as string,
    });

    res.json(fuelGrades);
  } catch (error) {
    console.error('Get fuel grades error:', error);
    res.status(500).json({ error: 'Failed to retrieve fuel grades' });
  }
});

router.get('/items', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate, startDate, endDate, limit } = req.query;

    const items = await storage.getSalesItemsByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      startDate: startDate as string,
      endDate: endDate as string,
      limit: limit ? parseInt(limit as string) : undefined,
    });

    res.json(items);
  } catch (error) {
    console.error('Get items error:', error);
    res.status(500).json({ error: 'Failed to retrieve items' });
  }
});

router.get('/departments', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate, startDate, endDate } = req.query;

    const departments = await storage.getSalesDepartmentsByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      startDate: startDate as string,
      endDate: endDate as string,
    });

    res.json(departments);
  } catch (error) {
    console.error('Get departments error:', error);
    res.status(500).json({ error: 'Failed to retrieve departments' });
  }
});

router.get('/summary', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate, startDate, endDate } = req.query;

    const summary = await storage.getSalesSummary({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      startDate: startDate as string,
      endDate: endDate as string,
    });

    res.json(summary);
  } catch (error) {
    console.error('Get sales summary error:', error);
    res.status(500).json({ error: 'Failed to retrieve sales summary' });
  }
});

// ============================================
// COMPREHENSIVE REPORT ENDPOINTS (11 DATAFRAMES)
// ============================================

router.get('/reports/store-summary', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate } = req.query;

    if (!businessDate) {
      return res.status(400).json({ error: 'businessDate is required' });
    }

    const rawXml = await storage.getRawXmlByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      reportType: 'CPJR',
    });

    if (rawXml.length === 0) {
      return res.json({
        storeName: 'No Data',
        voidCount: 0,
        voidAmount: 0,
        noSaleCount: 0,
        noSaleAmount: 0,
        errorCorrectCount: 0,
        errorCorrectAmount: 0,
      });
    }

    const cpjrData = await parseCPJR(rawXml[0].xmlContent, businessDate as string);

    res.json({
      storeName: 'Birdies Gas Station',
      voidCount: cpjrData.summary.voidCount,
      voidAmount: cpjrData.summary.voidAmount,
      noSaleCount: cpjrData.summary.noSaleCount,
      noSaleAmount: 0,
      errorCorrectCount: 0,
      errorCorrectAmount: 0,
    });
  } catch (error) {
    console.error('Store summary report error:', error);
    res.status(500).json({ error: 'Failed to generate store summary report' });
  }
});

router.get('/reports/fuel-dispensers', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate } = req.query;

    if (!businessDate) {
      return res.status(400).json({ error: 'businessDate is required' });
    }

    const rawXml = await storage.getRawXmlByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
      reportType: 'CPJR',
    });

    if (rawXml.length === 0) {
      return res.json([]);
    }

    const cpjrData = await parseCPJR(rawXml[0].xmlContent, businessDate as string);

    const dispensers = cpjrData.dispensers.map(d => ({
      pumpNumber: d.pumpNumber,
      count: d.count,
      amount: d.amount,
      volume: d.volume,
    }));

    res.json(dispensers);
  } catch (error) {
    console.error('Fuel dispensers report error:', error);
    res.status(500).json({ error: 'Failed to generate fuel dispensers report' });
  }
});

router.get('/reports/loyalty-details', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate } = req.query;

    if (!businessDate) {
      return res.status(400).json({ error: 'businessDate is required' });
    }

    const loyaltyUsage = await storage.getSalesLoyaltyUsageByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
    });

    res.json(loyaltyUsage);
  } catch (error) {
    console.error('Loyalty details report error:', error);
    res.status(500).json({ error: 'Failed to generate loyalty details report' });
  }
});

router.get('/reports/loyalty-overview', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate } = req.query;

    if (!businessDate) {
      return res.status(400).json({ error: 'businessDate is required' });
    }

    const loyaltyUsage = await storage.getSalesLoyaltyUsageByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
    });

    const totalPromotions = loyaltyUsage.length;
    const totalPromotionAmount = loyaltyUsage.reduce((sum, l) => sum + parseFloat(l.promotionAmount.toString()), 0);

    res.json({
      totalPromotions,
      totalPromotionAmount,
      averagePromotionAmount: totalPromotions > 0 ? totalPromotionAmount / totalPromotions : 0,
    });
  } catch (error) {
    console.error('Loyalty overview report error:', error);
    res.status(500).json({ error: 'Failed to generate loyalty overview report' });
  }
});

router.get('/reports/transaction-line-items', async (req: Request, res: Response) => {
  try {
    const { pdiStoreNumber, businessDate } = req.query;

    if (!businessDate) {
      return res.status(400).json({ error: 'businessDate is required' });
    }

    const lineItems = await storage.getSalesLineItemsByFilters({
      pdiStoreNumber: pdiStoreNumber as string,
      businessDate: businessDate as string,
    });

    res.json(lineItems);
  } catch (error) {
    console.error('Transaction line items report error:', error);
    res.status(500).json({ error: 'Failed to generate transaction line items report' });
  }
});

router.get('/reports/fuel-by-grade', async (req: Request, res: Response) => {
  try {
    const filters = parseFilters(req);
    const { pdiStoreNumber } = req.query;

    if (!filters.businessDate && !filters.startDate) {
      return res.status(400).json({ error: 'businessDate or startDate is required' });
    }

    const storeNumbers = pdiStoreNumber && typeof pdiStoreNumber === 'string' && pdiStoreNumber.includes(',')
      ? pdiStoreNumber.split(',').map(s => s.trim())
      : [];

    // Daily breakdown mode
    if (!filters.aggregate && filters.startDate && filters.endDate) {
      const dates = getDatesInRange(filters.startDate, filters.endDate);
      const dailyResults = await Promise.all(
        dates.map(async (date) => {
          const dateFilters = { ...filters, businessDate: date, startDate: undefined, endDate: undefined };
          
          const fuelGrades = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesFuelGradesByFilters(f)
          );

          return fuelGrades.map(fg => ({
            businessDate: date,
            gradeId: fg.gradeId,
            gradeName: fg.gradeName,
            volume: fg.volume,
            amount: fg.amount,
            discountAmount: fg.discountAmount,
          }));
        })
      );
      return res.json(dailyResults.flat());
    }

    // Aggregated mode (default)
    const fuelGrades = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesFuelGradesByFilters(f)
    );

    res.json(fuelGrades);
  } catch (error) {
    console.error('Fuel by grade report error:', error);
    res.status(500).json({ error: 'Failed to generate fuel by grade report' });
  }
});

router.get('/reports/aggregated-items', async (req: Request, res: Response) => {
  try {
    const filters = parseFilters(req);
    const { pdiStoreNumber } = req.query;

    if (!filters.businessDate && !filters.startDate) {
      return res.status(400).json({ error: 'businessDate or startDate is required' });
    }

    const storeNumbers = pdiStoreNumber && typeof pdiStoreNumber === 'string' && pdiStoreNumber.includes(',')
      ? pdiStoreNumber.split(',').map(s => s.trim())
      : [];

    // Daily breakdown mode
    if (!filters.aggregate && filters.startDate && filters.endDate) {
      const dates = getDatesInRange(filters.startDate, filters.endDate);
      const dailyResults = await Promise.all(
        dates.map(async (date) => {
          const dateFilters = { ...filters, businessDate: date, startDate: undefined, endDate: undefined };
          
          // Query both Passport items AND Verifone line items
          const items = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesItemsByFilters(f)
          );

          const lineItems = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesLineItemsByFilters(f)
          );

          // Combine items from both sources
          const allItems = [
            ...items.map(i => ({ upc: i.upc, description: i.description, quantity: i.quantity.toString(), salesAmount: i.salesAmount.toString() })),
            ...lineItems.filter(li => li.itemType !== 'fuel').map(li => ({ upc: li.upc, description: li.description, quantity: li.quantity.toString(), salesAmount: li.amount.toString() }))
          ];

          const aggregatedItems = allItems.reduce((acc, item) => {
            // Key by both UPC and description to handle null UPCs correctly
            const existingItem = acc.find(i => i.upc === item.upc && i.description === item.description);
            if (existingItem) {
              existingItem.quantity = (parseFloat(existingItem.quantity) + parseFloat(item.quantity)).toString();
              existingItem.salesAmount = (parseFloat(existingItem.salesAmount) + parseFloat(item.salesAmount)).toString();
            } else {
              acc.push({ ...item });
            }
            return acc;
          }, [] as Array<{ upc: string; description: string; quantity: string; salesAmount: string }>);

          aggregatedItems.sort((a, b) => parseFloat(b.salesAmount) - parseFloat(a.salesAmount));

          return aggregatedItems.map(item => ({
            businessDate: date,
            upc: item.upc,
            description: item.description,
            quantity: item.quantity,
            salesAmount: item.salesAmount,
          }));
        })
      );
      return res.json(dailyResults.flat());
    }

    // Aggregated mode (default)
    // Query both Passport items AND Verifone line items
    const items = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesItemsByFilters(f)
    );

    const lineItems = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesLineItemsByFilters(f)
    );

    // Combine items from both sources
    const allItems = [
      ...items.map(i => ({ upc: i.upc, description: i.description, quantity: i.quantity.toString(), salesAmount: i.salesAmount.toString() })),
      ...lineItems.filter(li => li.itemType !== 'fuel').map(li => ({ upc: li.upc, description: li.description, quantity: li.quantity.toString(), salesAmount: li.amount.toString() }))
    ];

    const aggregatedItems = allItems.reduce((acc, item) => {
      // Key by both UPC and description to handle null UPCs correctly (e.g., PREPAY items)
      const existingItem = acc.find(i => i.upc === item.upc && i.description === item.description);
      if (existingItem) {
        existingItem.quantity = (parseFloat(existingItem.quantity) + parseFloat(item.quantity)).toString();
        existingItem.salesAmount = (parseFloat(existingItem.salesAmount) + parseFloat(item.salesAmount)).toString();
      } else {
        acc.push({ ...item });
      }
      return acc;
    }, [] as Array<{ upc: string; description: string; quantity: string; salesAmount: string }>);

    aggregatedItems.sort((a, b) => parseFloat(b.salesAmount) - parseFloat(a.salesAmount));

    res.json(aggregatedItems);
  } catch (error) {
    console.error('Aggregated items report error:', error);
    res.status(500).json({ error: 'Failed to generate aggregated items report' });
  }
});

router.get('/reports/daily-fuel-sales', async (req: Request, res: Response) => {
  try {
    const filters = parseFilters(req);
    const { pdiStoreNumber } = req.query;

    if (!filters.businessDate && !filters.startDate) {
      return res.status(400).json({ error: 'businessDate or startDate is required' });
    }

    const storeNumbers = pdiStoreNumber && typeof pdiStoreNumber === 'string' && pdiStoreNumber.includes(',')
      ? pdiStoreNumber.split(',').map(s => s.trim())
      : [];

    // Daily breakdown mode
    if (!filters.aggregate && filters.startDate && filters.endDate) {
      const dates = getDatesInRange(filters.startDate, filters.endDate);
      const dailyResults = await Promise.all(
        dates.map(async (date) => {
          const dateFilters = { ...filters, businessDate: date, startDate: undefined, endDate: undefined };
          
          // Query both Passport fuel grades AND Verifone transactions
          const fuelGrades = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesFuelGradesByFilters(f)
          );

          const transactions = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesTransactionsByFilters(f)
          );

          // Combine Passport and Verifone data
          const passportVolume = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.volume.toString()), 0);
          const passportAmount = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.amount.toString()), 0);
          const passportDiscount = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.discountAmount.toString()), 0);

          const verifoneVolume = transactions.reduce((sum, t) => sum + parseFloat(t.fuelVolume.toString()), 0);
          const verifoneAmount = transactions.reduce((sum, t) => sum + parseFloat(t.fuelAmount.toString()), 0);

          const totalVolume = passportVolume + verifoneVolume;
          const totalAmount = passportAmount + verifoneAmount;
          const totalDiscount = passportDiscount;

          return {
            businessDate: date,
            totalVolume,
            totalAmount,
            totalDiscount,
            netAmount: totalAmount - totalDiscount,
          };
        })
      );
      return res.json(dailyResults);
    }

    // Aggregated mode (default)
    // Query both Passport fuel grades AND Verifone transactions
    const fuelGrades = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesFuelGradesByFilters(f)
    );

    const transactions = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesTransactionsByFilters(f)
    );

    // Passport data
    const passportVolume = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.volume.toString()), 0);
    const passportAmount = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.amount.toString()), 0);
    const passportDiscount = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.discountAmount.toString()), 0);

    // Verifone data (from transactions)
    const verifoneVolume = transactions.reduce((sum, t) => sum + parseFloat(t.fuelVolume.toString()), 0);
    const verifoneAmount = transactions.reduce((sum, t) => sum + parseFloat(t.fuelAmount.toString()), 0);

    // Guardrail: Warn if both sources have data (potential double-counting)
    if (fuelGrades.length > 0 && transactions.length > 0) {
      console.warn(`[SALES] Both Passport and Verifone data found. Verify no double-counting.`);
    }

    const totalVolume = passportVolume + verifoneVolume;
    const totalAmount = passportAmount + verifoneAmount;
    const totalDiscount = passportDiscount; // Verifone doesn't track discounts separately

    res.json({
      businessDate: filters.businessDate || `${filters.startDate} to ${filters.endDate}`,
      totalVolume,
      totalAmount,
      totalDiscount,
      netAmount: totalAmount - totalDiscount,
    });
  } catch (error) {
    console.error('Daily fuel sales report error:', error);
    res.status(500).json({ error: 'Failed to generate daily fuel sales report' });
  }
});

router.get('/reports/daily-total-sales', async (req: Request, res: Response) => {
  try {
    const filters = parseFilters(req);
    const { pdiStoreNumber } = req.query;

    if (!filters.businessDate && !filters.startDate) {
      return res.status(400).json({ error: 'businessDate or startDate is required' });
    }

    const storeNumbers = pdiStoreNumber && typeof pdiStoreNumber === 'string' && pdiStoreNumber.includes(',')
      ? pdiStoreNumber.split(',').map(s => s.trim())
      : [];

    // Daily breakdown mode
    if (!filters.aggregate && filters.startDate && filters.endDate) {
      const dates = getDatesInRange(filters.startDate, filters.endDate);
      const dailyResults = await Promise.all(
        dates.map(async (date) => {
          const dateFilters = { ...filters, businessDate: date, startDate: undefined, endDate: undefined };
          
          // Query both Passport tables AND transactions (for Verifone)
          const fuelGrades = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesFuelGradesByFilters(f)
          );

          const items = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesItemsByFilters(f)
          );

          const transactions = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesTransactionsByFilters(f)
          );

          // Combine Passport and Verifone data
          const passportFuel = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.amount.toString()), 0);
          const passportMerch = items.reduce((sum, item) => sum + parseFloat(item.salesAmount.toString()), 0);
          const verifoneFuel = transactions.reduce((sum, t) => sum + parseFloat(t.fuelAmount.toString()), 0);
          const verifoneMerch = transactions.reduce((sum, t) => sum + parseFloat(t.merchAmount.toString()), 0);

          const fuelAmount = passportFuel + verifoneFuel;
          const merchAmount = passportMerch + verifoneMerch;

          return {
            businessDate: date,
            fuelAmount,
            merchAmount,
            totalAmount: fuelAmount + merchAmount,
          };
        })
      );
      return res.json(dailyResults);
    }

    // Aggregated mode (default)
    // Query both Passport-specific tables AND transaction table (for Verifone)
    const fuelGrades = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesFuelGradesByFilters(f)
    );

    const items = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesItemsByFilters(f)
    );

    const transactions = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesTransactionsByFilters(f)
    );

    // Sum from Passport data (Gilbarco)
    const passportFuel = fuelGrades.reduce((sum, fg) => sum + parseFloat(fg.amount.toString()), 0);
    const passportMerch = items.reduce((sum, item) => sum + parseFloat(item.salesAmount.toString()), 0);

    // Sum from transaction data (Verifone CPJR)
    const verifoneFuel = transactions.reduce((sum, t) => sum + parseFloat(t.fuelAmount.toString()), 0);
    const verifoneMerch = transactions.reduce((sum, t) => sum + parseFloat(t.merchAmount.toString()), 0);

    const fuelAmount = passportFuel + verifoneFuel;
    const merchAmount = passportMerch + verifoneMerch;

    res.json({
      businessDate: filters.businessDate || `${filters.startDate} to ${filters.endDate}`,
      fuelAmount,
      merchAmount,
      totalAmount: fuelAmount + merchAmount,
    });
  } catch (error) {
    console.error('Daily total sales report error:', error);
    res.status(500).json({ error: 'Failed to generate daily total sales report' });
  }
});

router.get('/reports/department-sales', async (req: Request, res: Response) => {
  try {
    const filters = parseFilters(req);
    const { pdiStoreNumber } = req.query;

    if (!filters.businessDate && !filters.startDate) {
      return res.status(400).json({ error: 'businessDate or startDate is required' });
    }

    const storeNumbers = pdiStoreNumber && typeof pdiStoreNumber === 'string' && pdiStoreNumber.includes(',')
      ? pdiStoreNumber.split(',').map(s => s.trim())
      : [];

    // Daily breakdown mode
    if (!filters.aggregate && filters.startDate && filters.endDate) {
      const dates = getDatesInRange(filters.startDate, filters.endDate);
      const dailyResults = await Promise.all(
        dates.map(async (date) => {
          const dateFilters = { ...filters, businessDate: date, startDate: undefined, endDate: undefined };
          
          const departments = await aggregateDataAcrossStores(
            storeNumbers,
            dateFilters,
            (f) => storage.getSalesDepartmentsByFilters(f)
          );

          const departmentMap = new Map<string, {
            departmentCode: string;
            departmentName: string;
            salesAmount: number;
            quantity: number;
            transactionCount: number;
          }>();

          departments.forEach(dept => {
            const deptMapping = getDepartmentForCategory(dept.departmentCode);
            const deptCode = deptMapping?.departmentCode || dept.departmentCode;
            const deptName = deptMapping?.departmentName || dept.departmentName;

            const existing = departmentMap.get(deptCode);
            if (existing) {
              existing.salesAmount += parseFloat(dept.salesAmount.toString());
              existing.quantity += parseFloat(dept.quantity.toString());
              existing.transactionCount += dept.transactionCount;
            } else {
              departmentMap.set(deptCode, {
                departmentCode: deptCode,
                departmentName: deptName,
                salesAmount: parseFloat(dept.salesAmount.toString()),
                quantity: parseFloat(dept.quantity.toString()),
                transactionCount: dept.transactionCount,
              });
            }
          });

          const departmentSales = Array.from(departmentMap.values()).sort((a, b) => b.salesAmount - a.salesAmount);

          return departmentSales.map(dept => ({
            businessDate: date,
            departmentCode: dept.departmentCode,
            departmentName: dept.departmentName,
            salesAmount: dept.salesAmount,
            quantity: dept.quantity,
            transactionCount: dept.transactionCount,
          }));
        })
      );
      return res.json(dailyResults.flat());
    }

    // Aggregated mode (default)
    const departments = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesDepartmentsByFilters(f)
    );

    const departmentMap = new Map<string, {
      departmentCode: string;
      departmentName: string;
      salesAmount: number;
      quantity: number;
      transactionCount: number;
    }>();

    departments.forEach(dept => {
      const deptMapping = getDepartmentForCategory(dept.departmentCode);
      const deptCode = deptMapping?.departmentCode || dept.departmentCode;
      const deptName = deptMapping?.departmentName || dept.departmentName;

      const existing = departmentMap.get(deptCode);
      if (existing) {
        existing.salesAmount += parseFloat(dept.salesAmount.toString());
        existing.quantity += parseFloat(dept.quantity.toString());
        existing.transactionCount += dept.transactionCount;
      } else {
        departmentMap.set(deptCode, {
          departmentCode: deptCode,
          departmentName: deptName,
          salesAmount: parseFloat(dept.salesAmount.toString()),
          quantity: parseFloat(dept.quantity.toString()),
          transactionCount: dept.transactionCount,
        });
      }
    });

    const departmentSales = Array.from(departmentMap.values()).sort((a, b) => b.salesAmount - a.salesAmount);

    res.json(departmentSales);
  } catch (error) {
    console.error('Department sales report error:', error);
    res.status(500).json({ error: 'Failed to generate department sales report' });
  }
});

router.get('/reports/unknown-items', async (req: Request, res: Response) => {
  try {
    const filters = parseFilters(req);
    const { pdiStoreNumber } = req.query;

    if (!filters.businessDate && !filters.startDate) {
      return res.status(400).json({ error: 'businessDate or startDate is required' });
    }

    const storeNumbers = pdiStoreNumber && typeof pdiStoreNumber === 'string' && pdiStoreNumber.includes(',')
      ? pdiStoreNumber.split(',').map(s => s.trim())
      : [];

    // Query both Passport items AND Verifone line items
    const items = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesItemsByFilters(f)
    );

    const lineItems = await aggregateDataAcrossStores(
      storeNumbers,
      filters,
      (f) => storage.getSalesLineItemsByFilters(f)
    );

    // Combine all items and deduplicate UPCs first (performance optimization)
    const allItems = [
      ...items.map(i => ({ upc: i.upc, description: i.description, pdiStoreNumber: i.pdiStoreNumber, quantity: i.quantity.toString(), revenue: i.salesAmount.toString() })),
      ...lineItems.map(li => ({ upc: li.upc, description: li.description, pdiStoreNumber: li.pdiStoreNumber, quantity: li.quantity.toString(), revenue: li.amount.toString() }))
    ];

    // Get unique UPCs to reduce pricebook queries
    const uniqueUpcs = [...new Set(allItems.map(item => item.upc))];
    
    // Batch lookup all UPCs in pricebook
    const pricebookMap = new Map<string, boolean>();
    for (const upc of uniqueUpcs) {
      const pricebookItems = await storage.searchPricebook(upc);
      const exactMatch = pricebookItems.find(p => p.upc === upc);
      pricebookMap.set(upc, !!exactMatch);
    }

    // Cache location lookups
    const locationCache = new Map<string, string>();

    const unknownItemsMap = new Map<string, {
      upc: string;
      description: string;
      pdiStoreNumber: string;
      storeName: string;
      timesSold: number;
      totalQuantity: number;
      totalRevenue: number;
    }>();

    // Process all items using cached pricebook lookups
    for (const item of allItems) {
      const isInPricebook = pricebookMap.get(item.upc);
      
      if (!isInPricebook) {
        const key = `${item.upc}-${item.pdiStoreNumber}`;
        
        // Get location name from cache or fetch
        let storeName = locationCache.get(item.pdiStoreNumber);
        if (!storeName) {
          const location = await storage.getLocationByPdiStoreNumber(item.pdiStoreNumber);
          storeName = location?.locationName || `Store ${item.pdiStoreNumber}`;
          locationCache.set(item.pdiStoreNumber, storeName);
        }
        
        const existing = unknownItemsMap.get(key);
        if (existing) {
          existing.timesSold += 1;
          existing.totalQuantity += parseFloat(item.quantity);
          existing.totalRevenue += parseFloat(item.revenue);
        } else {
          unknownItemsMap.set(key, {
            upc: item.upc,
            description: item.description,
            pdiStoreNumber: item.pdiStoreNumber,
            storeName,
            timesSold: 1,
            totalQuantity: parseFloat(item.quantity),
            totalRevenue: parseFloat(item.revenue),
          });
        }
      }
    }

    const unknownItems = Array.from(unknownItemsMap.values()).sort((a, b) => b.totalRevenue - a.totalRevenue);

    res.json(unknownItems);
  } catch (error) {
    console.error('Unknown items report error:', error);
    res.status(500).json({ error: 'Failed to generate unknown items report' });
  }
});

// Verifone Fuel Grade Sales Report - parses CPJR XML directly
router.get('/reports/verifone-fuel-grades', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate } = req.query;
    
    if (!storeNumber || !startDate) {
      return res.status(400).json({ error: 'storeNumber and startDate are required' });
    }
    
    const pdiStoreNumber = storeNumber as string;
    const dateStart = startDate as string;
    const dateEnd = (endDate as string) || dateStart;
    
    // Get all CPJR XML files for the store and date range
    const rawXmlRecords = await storage.getRawXmlByFilters({
      pdiStoreNumber,
      startDate: dateStart,
      endDate: dateEnd
    });
    
    const cpjrRecords = rawXmlRecords.filter(r => r.reportType === 'CPJR');
    
    if (cpjrRecords.length === 0) {
      return res.json({ 
        fuelGrades: [], 
        summary: { totalGrades: 0, totalVolume: 0, totalSalesAmount: 0, totalTransactions: 0, averagePricePerGallon: 0 },
        message: 'No CPJR data found for the specified store and date range'
      });
    }
    
    // Parse all CPJR files and combine results
    const fuelGradeMap = new Map<string, any>();
    
    for (const record of cpjrRecords) {
      const result = await parseVerifoneFuelGradesFromCPJR(record.xmlContent, record.businessDate);
      
      for (const grade of result.fuelGrades) {
        const key = grade.gradeCode;
        
        if (fuelGradeMap.has(key)) {
          const existing = fuelGradeMap.get(key);
          existing.volume += grade.volume;
          existing.salesAmount += grade.salesAmount;
          existing.transactionCount += grade.transactionCount;
        } else {
          fuelGradeMap.set(key, { ...grade });
        }
      }
    }
    
    // Recalculate average prices
    const fuelGrades = Array.from(fuelGradeMap.values()).map(grade => ({
      ...grade,
      averagePrice: grade.volume > 0 ? grade.salesAmount / grade.volume : 0
    }));
    
    // Sort by sales amount descending
    fuelGrades.sort((a, b) => b.salesAmount - a.salesAmount);
    
    const totalVolume = fuelGrades.reduce((sum, g) => sum + g.volume, 0);
    const totalSalesAmount = fuelGrades.reduce((sum, g) => sum + g.salesAmount, 0);
    
    const summary = {
      totalGrades: fuelGrades.length,
      totalVolume: totalVolume,
      totalSalesAmount: totalSalesAmount,
      totalTransactions: fuelGrades.reduce((sum, g) => sum + g.transactionCount, 0),
      averagePricePerGallon: totalVolume > 0 ? totalSalesAmount / totalVolume : 0
    };
    
    res.json({ fuelGrades, summary });
  } catch (error) {
    console.error('Verifone fuel grade report error:', error);
    res.status(500).json({ error: 'Failed to generate Verifone fuel grade report' });
  }
});

// Verifone Department Sales Report - parses CPJR XML directly
router.get('/reports/verifone-departments', async (req: Request, res: Response) => {
  try {
    const { storeNumber, startDate, endDate, groupBy } = req.query;
    
    if (!storeNumber || !startDate) {
      return res.status(400).json({ error: 'storeNumber and startDate are required' });
    }
    
    const pdiStoreNumber = storeNumber as string;
    const dateStart = startDate as string;
    const dateEnd = (endDate as string) || dateStart;
    const groupByDept = groupBy === 'department';
    
    // Get all CPJR XML files for the store and date range
    const rawXmlRecords = await storage.getRawXmlByFilters({
      pdiStoreNumber,
      startDate: dateStart,
      endDate: dateEnd
    });
    
    const cpjrRecords = rawXmlRecords.filter(r => r.reportType === 'CPJR');
    
    if (cpjrRecords.length === 0) {
      return res.json({ 
        departments: [], 
        summary: { totalCategories: 0, totalDepartments: 0, totalSalesAmount: 0, totalItems: 0 },
        message: 'No CPJR data found for the specified store and date range'
      });
    }
    
    // Parse all CPJR files and combine results
    let allDepartments: any[] = [];
    
    for (const record of cpjrRecords) {
      const result = await parseVerifoneDepartmentsFromCPJR(record.xmlContent, record.businessDate);
      
      // Add business date to each department record
      for (const dept of result.departments) {
        allDepartments.push({
          ...dept,
          businessDate: record.businessDate
        });
      }
    }
    
    // Optionally aggregate by department code
    if (groupByDept) {
      allDepartments = aggregateByDepartment(allDepartments);
    }
    
    // Sort by sales amount descending
    allDepartments.sort((a, b) => b.salesAmount - a.salesAmount);
    
    const summary = {
      totalCategories: allDepartments.length,
      totalDepartments: new Set(allDepartments.map(d => d.departmentCode)).size,
      totalSalesAmount: allDepartments.reduce((sum, d) => sum + d.salesAmount, 0),
      totalItems: allDepartments.reduce((sum, d) => sum + d.quantity, 0)
    };
    
    res.json({ departments: allDepartments, summary });
  } catch (error) {
    console.error('Verifone department report error:', error);
    res.status(500).json({ error: 'Failed to generate Verifone department report' });
  }
});

// ============================================
// FINAL VERIFONE PARSER - Comprehensive Report
// ============================================

router.get('/reports/verifone-full-day', async (req: Request, res: Response) => {
  try {
    const { storeNumber, businessDate } = req.query;
    
    if (!storeNumber || !businessDate) {
      return res.status(400).json({ error: 'storeNumber and businessDate are required' });
    }
    
    const pdiStoreNumber = storeNumber as string;
    const date = businessDate as string;
    
    const rawXmlRecords = await storage.getRawXmlByFilters({
      pdiStoreNumber,
      businessDate: date
    });
    
    const cpjrRecord = rawXmlRecords.find(r => r.reportType === 'CPJR');
    
    if (!cpjrRecord) {
      return res.status(404).json({ 
        error: 'No CPJR data found for the specified store and date',
        storeNumber: pdiStoreNumber,
        businessDate: date
      });
    }
    
    const report = await generateVerifoneFullDayReport(
      cpjrRecord.xmlContent,
      date,
      pdiStoreNumber
    );
    
    res.json(report);
  } catch (error) {
    console.error('Verifone full day report error:', error);
    res.status(500).json({ error: 'Failed to generate Verifone full day report' });
  }
});

router.get('/reports/verifone-transactions', async (req: Request, res: Response) => {
  try {
    const { storeNumber, businessDate, limit } = req.query;
    
    if (!storeNumber || !businessDate) {
      return res.status(400).json({ error: 'storeNumber and businessDate are required' });
    }
    
    const pdiStoreNumber = storeNumber as string;
    const date = businessDate as string;
    const maxResults = parseInt(limit as string) || 100;
    
    const rawXmlRecords = await storage.getRawXmlByFilters({
      pdiStoreNumber,
      businessDate: date
    });
    
    const cpjrRecord = rawXmlRecords.find(r => r.reportType === 'CPJR');
    
    if (!cpjrRecord) {
      return res.status(404).json({ 
        error: 'No CPJR data found',
        storeNumber: pdiStoreNumber,
        businessDate: date
      });
    }
    
    const result = await parseVerifoneTransactionJournal(cpjrRecord.xmlContent, date);
    
    const transactions = result.transactions.slice(0, maxResults);
    
    res.json({
      transactions,
      summary: result.summary,
      pagination: {
        returned: transactions.length,
        total: result.transactions.length,
        limit: maxResults
      }
    });
  } catch (error) {
    console.error('Verifone transactions report error:', error);
    res.status(500).json({ error: 'Failed to generate Verifone transactions report' });
  }
});

router.get('/reports/verifone-fgm-cumulative', async (req: Request, res: Response) => {
  try {
    const { storeNumber, businessDate } = req.query;
    
    if (!storeNumber || !businessDate) {
      return res.status(400).json({ error: 'storeNumber and businessDate are required' });
    }
    
    const pdiStoreNumber = storeNumber as string;
    const date = businessDate as string;
    
    const rawXmlRecords = await storage.getRawXmlByFilters({
      pdiStoreNumber,
      businessDate: date
    });
    
    const fgmRecord = rawXmlRecords.find(r => r.reportType === 'FGM');
    
    if (!fgmRecord) {
      return res.status(404).json({ 
        error: 'No FGM data found',
        storeNumber: pdiStoreNumber,
        businessDate: date,
        hint: 'Verifone FGM files contain cumulative meter readings'
      });
    }
    
    const readings = await parseVerifoneFGMCumulative(fgmRecord.xmlContent, pdiStoreNumber);
    
    res.json({
      storeNumber: pdiStoreNumber,
      businessDate: date,
      readings,
      note: 'These are cumulative lifetime readings. Use /verifone-fgm-daily to calculate daily sales by differencing.'
    });
  } catch (error) {
    console.error('Verifone FGM cumulative report error:', error);
    res.status(500).json({ error: 'Failed to parse Verifone FGM cumulative data' });
  }
});

router.get('/reports/verifone-fgm-daily', async (req: Request, res: Response) => {
  try {
    const { storeNumber, businessDate } = req.query;
    
    if (!storeNumber || !businessDate) {
      return res.status(400).json({ error: 'storeNumber and businessDate are required' });
    }
    
    const pdiStoreNumber = storeNumber as string;
    const date = businessDate as string;
    
    const previousDate = new Date(date);
    previousDate.setDate(previousDate.getDate() - 1);
    const prevDateStr = previousDate.toISOString().split('T')[0];
    
    const [todayRecords, yesterdayRecords] = await Promise.all([
      storage.getRawXmlByFilters({ pdiStoreNumber, businessDate: date }),
      storage.getRawXmlByFilters({ pdiStoreNumber, businessDate: prevDateStr })
    ]);
    
    const todayFgm = todayRecords.find(r => r.reportType === 'FGM');
    const yesterdayFgm = yesterdayRecords.find(r => r.reportType === 'FGM');
    
    if (!todayFgm) {
      return res.status(404).json({ 
        error: 'No FGM data found for the specified date',
        storeNumber: pdiStoreNumber,
        businessDate: date
      });
    }
    
    const closingReadings = await parseVerifoneFGMCumulative(todayFgm.xmlContent, pdiStoreNumber);
    
    if (!yesterdayFgm) {
      const cpjrRecord = todayRecords.find(r => r.reportType === 'CPJR');
      
      if (cpjrRecord) {
        const cpjrResult = await parseVerifoneTransactionJournal(cpjrRecord.xmlContent, date);
        
        return res.json({
          businessDate: date,
          pdiStoreNumber,
          calculatedFrom: 'cpjr_transactions',
          note: 'No previous day FGM data available. Using CPJR transaction totals instead.',
          totals: {
            totalVolume: cpjrResult.summary.totalFuelVolume,
            totalAmount: cpjrResult.summary.totalFuelAmount
          },
          closingReadings
        });
      }
      
      return res.json({
        businessDate: date,
        pdiStoreNumber,
        calculatedFrom: 'single_reading',
        note: 'No previous day FGM data available. Cannot calculate daily totals by differencing.',
        closingReadings
      });
    }
    
    const openingReadings = await parseVerifoneFGMCumulative(yesterdayFgm.xmlContent, pdiStoreNumber);
    
    const dailyCalculation = calculateDailyFuelFromCumulativeReadings(
      openingReadings,
      closingReadings,
      date,
      pdiStoreNumber
    );
    
    res.json(dailyCalculation);
  } catch (error) {
    console.error('Verifone FGM daily report error:', error);
    res.status(500).json({ error: 'Failed to calculate Verifone daily fuel sales' });
  }
});

export default router;
