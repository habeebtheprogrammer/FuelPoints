import { parseStringPromise } from 'xml2js';
import type { FuelGradeData, ItemSalesData, DepartmentData } from './passportParsers';

const VERIFONE_FUEL_GRADE_MAPPING: Record<string, { id: string; name: string }> = {
  '1': { id: '001', name: 'Regular' },
  '2': { id: '002', name: 'Plus/Mid-Grade' },
  '3': { id: '003', name: 'Premium' },
  '4': { id: '004', name: 'Super Premium' },
  '19': { id: '019', name: 'Diesel' },
  '7': { id: '019', name: 'Diesel' },
  '9': { id: '009', name: 'Kerosene' },
  '8': { id: '009', name: 'Kerosene' },
};

export async function parseVerifoneFGM(xmlContent: string, businessDate: string): Promise<FuelGradeData[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    const fuelTotals = result['fuel:fuelTotals'];
    
    if (!fuelTotals || !fuelTotals.fpDispenserData) {
      throw new Error('Invalid Verifone fuel totals XML structure');
    }

    const dispenserData = fuelTotals.fpDispenserData;
    const gradeMap = new Map<string, FuelGradeData>();

    for (const dispenser of dispenserData) {
      const productID = dispenser.productID?.[0] || '';
      const productNumberData = dispenser.productNumber?.[0];
      const productName = typeof productNumberData === 'object' ? productNumberData.$.name : productNumberData;
      
      const volumeData = dispenser.fuelVolume?.[0];
      const amountData = dispenser.fuelMoney?.[0];
      
      const volume = parseFloat(typeof volumeData === 'object' ? volumeData._ || '0' : volumeData || '0');
      const amount = parseFloat(typeof amountData === 'object' ? amountData._ || '0' : amountData || '0');
      
      if (!productID) continue;

      const gradeInfo = VERIFONE_FUEL_GRADE_MAPPING[productID];
      const gradeId = gradeInfo?.id || String(productID).padStart(3, '0');
      const gradeName = gradeInfo?.name || productName || `Grade ${productID}`;

      if (gradeMap.has(gradeId)) {
        const existing = gradeMap.get(gradeId)!;
        existing.volume += volume;
        existing.amount += amount;
      } else {
        gradeMap.set(gradeId, {
          gradeId,
          gradeName,
          volume,
          amount,
          discountAmount: 0,
        });
      }
    }

    return Array.from(gradeMap.values());
  } catch (error) {
    console.error('Error parsing Verifone FGM XML:', error);
    throw new Error(`Failed to parse Verifone FGM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function parseVerifoneISM(xmlContent: string, businessDate: string): Promise<{ items: ItemSalesData[], departments: DepartmentData[] }> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    let productData: any[] = [];
    if (result['merch:allProductReport']) {
      productData = result['merch:allProductReport'].productData || [];
    } else if (result['allProductReport']) {
      productData = result['allProductReport'].productData || [];
    }

    const items: ItemSalesData[] = [];
    const departmentMap = new Map<string, DepartmentData>();

    for (const product of productData) {
      const upc = product.upc?.[0] || product.productNumber?.[0] || '';
      const description = product.productName?.[0] || product.description?.[0] || 'Unknown';
      const departmentCode = product.department?.[0] || product.categoryCode?.[0] || 'MISC';
      const departmentName = product.departmentName?.[0] || product.categoryName?.[0] || 'Miscellaneous';
      
      const quantity = parseFloat(product.quantitySold?.[0] || product.quantity?.[0] || '0');
      const salesAmount = parseFloat(product.salesAmount?.[0] || product.totalSales?.[0] || '0');

      if (upc && quantity > 0) {
        items.push({
          upc,
          description,
          quantity,
          salesAmount,
        });
      }

      if (departmentCode) {
        if (departmentMap.has(departmentCode)) {
          const existing = departmentMap.get(departmentCode)!;
          existing.quantity += quantity;
          existing.salesAmount += salesAmount;
          existing.transactionCount += 1;
        } else {
          departmentMap.set(departmentCode, {
            departmentCode,
            departmentName,
            salesAmount,
            quantity,
            transactionCount: 1,
          });
        }
      }
    }

    return { items, departments: Array.from(departmentMap.values()) };
  } catch (error) {
    console.error('Error parsing Verifone ISM XML:', error);
    throw new Error(`Failed to parse Verifone ISM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function parseVerifoneMCM(xmlContent: string, businessDate: string): Promise<DepartmentData[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    let categoryData: any[] = [];
    if (result['merch:categoryReport']) {
      categoryData = result['merch:categoryReport'].categoryData || [];
    } else if (result['categoryReport']) {
      categoryData = result['categoryReport'].categoryData || [];
    }

    const departments: DepartmentData[] = [];

    for (const category of categoryData) {
      const departmentCode = category.categoryCode?.[0] || category.departmentCode?.[0] || '';
      const departmentName = category.categoryName?.[0] || category.departmentName?.[0] || 'Unknown';
      const salesAmount = parseFloat(category.salesAmount?.[0] || category.totalSales?.[0] || '0');
      const quantity = parseFloat(category.quantitySold?.[0] || category.quantity?.[0] || '0');
      const transactionCount = parseInt(category.transactionCount?.[0] || '0', 10);

      if (departmentCode) {
        departments.push({
          departmentCode,
          departmentName,
          salesAmount,
          quantity,
          transactionCount,
        });
      }
    }

    return departments;
  } catch (error) {
    console.error('Error parsing Verifone MCM XML:', error);
    throw new Error(`Failed to parse Verifone MCM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export interface CPJRData {
  transactions: any[];
  lineItems: any[];
  loyalty: any[];
  summary: any;
  dispensers: any[];
}

export async function parseVerifoneCPJR(xmlContent: string, businessDate: string): Promise<CPJRData> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    // Verifone uses <transSet> as root element
    const transSet = result['transSet'];
    if (!transSet) {
      throw new Error('Invalid Verifone CPJR XML structure - expected <transSet> root element');
    }

    const transactions: any[] = [];
    const lineItems: any[] = [];
    let voidCount = 0;
    let voidAmount = 0;
    
    // Get all <trans> elements
    const transData = transSet.trans || [];
    
    // CRITICAL FIX: Verifone CPJR splits transactions into multiple <trans> fragments with same uniqueID
    // We must merge all fragments before processing
    const transactionMap = new Map<string, any>();

    for (const trans of transData) {
      const transType = trans.$?.type || '';
      
      // Only process sale transactions - skip voids, refunds, journal entries, etc.
      // Voids and refunds should be tracked separately if needed, not counted as sales
      if (transType !== 'sale') {
        // Track voids for summary statistics
        if (transType === 'void') {
          const trValue = trans.trValue?.[0];
          const voidTotal = parseFloat(trValue?.trCurrTot?.[0] || trValue?.trTotWTax?.[0] || '0');
          voidCount++;
          voidAmount += voidTotal;
        }
        continue;
      }
      
      // Get uniqueID to merge fragments
      const trHeader = trans.trHeader?.[0];
      const uniqueID = trHeader?.uniqueID?.[0] || trHeader?.trUniqueSN?.[0] || '';
      
      if (!uniqueID) {
        continue;
      }
      
      // Merge transaction fragments by uniqueID
      if (!transactionMap.has(uniqueID)) {
        transactionMap.set(uniqueID, trans);
      } else {
        // Merge trLines from this fragment into the main transaction
        const existingTrans = transactionMap.get(uniqueID);
        const existingLines = existingTrans.trLines?.[0]?.trLine || [];
        const newLines = trans.trLines?.[0]?.trLine || [];
        
        if (newLines.length > 0) {
          if (!existingTrans.trLines) {
            existingTrans.trLines = [{ trLine: [] }];
          }
          existingTrans.trLines[0].trLine = [...existingLines, ...newLines];
        }
      }
    }
    
    // Now process merged transactions
    for (const [uniqueID, trans] of transactionMap.entries()) {

      const trHeader = trans.trHeader?.[0];
      const trValue = trans.trValue?.[0];
      const trLines = trans.trLines?.[0];
      const trPaylines = trans.trPaylines?.[0];

      if (!trHeader || !trValue) {
        continue;
      }

      // Extract transaction header data (uniqueID already from map key)
      const trTickNum = trHeader.trTickNum?.[0];
      const sequenceNumber = parseInt(trTickNum?.trSeq?.[0] || '0', 10);
      const registerNumber = trTickNum?.posNum?.[0] || trHeader.posNum?.[0] || '0';
      const transactionDateTime = trHeader.date?.[0] || new Date().toISOString();
      const cashier = trHeader.cashier?.[0] || '';
      const cashierSysId = typeof cashier === 'object' ? (cashier.$?.sysid || null) : null;
      const cashierId = cashierSysId || registerNumber;

      // Extract transaction totals
      const totalAmount = parseFloat(trValue.trTotWTax?.[0] || trValue.trCurrTot?.[0] || '0');
      const subtotal = parseFloat(trValue.trTotNoTax?.[0] || '0');
      const taxAmount = parseFloat(trValue.trTotTax?.[0] || '0');

      // Extract tender/payment info
      let tenderType = 'UNKNOWN';
      if (trPaylines?.trPayline) {
        const payline = trPaylines.trPayline[0];
        const paycode = payline.trpPaycode?.[0];
        tenderType = typeof paycode === 'string' ? paycode : (paycode?._ || paycode?.$?.mop || 'UNKNOWN');
      }

      // Calculate fuel vs merchandise (Verifone doesn't always separate, so we'll analyze line items)
      let fuelAmount = 0;
      let merchAmount = 0;
      let fuelVolume = 0;

      // Extract line items
      if (trLines?.trLine) {
        for (const line of trLines.trLine) {
          const lineType = line.$?.type || 'unknown';
          const upc = line.trlUPC?.[0] || null;
          const description = line.trlDesc?.[0] || null;
          const quantity = parseFloat(line.trlQty?.[0] || '1');
          const lineTotal = parseFloat(line.trlLineTot?.[0] || '0');
          const deptInfo = line.trlDept?.[0];
          const departmentCode = typeof deptInfo === 'object' ? (deptInfo.$?.number || '') : '';
          
          // Determine if this is fuel or merchandise
          const isFuel = lineType === 'fuel' || (departmentCode && parseInt(departmentCode) >= 10 && parseInt(departmentCode) <= 19);
          
          // Track fuel vs merchandise
          if (isFuel) {
            fuelAmount += lineTotal;
            fuelVolume += quantity;
          } else {
            merchAmount += lineTotal;
          }

          if (uniqueID) {
            lineItems.push({
              posTransactionId: uniqueID,
              itemType: isFuel ? 'fuel' : 'merchandise',
              upc,
              description,
              pumpNumber: isFuel ? departmentCode : null,
              quantity,
              amount: lineTotal,
            });
          }
        }
      }

      // Handle edge case: transaction with total but no line items
      // NOTE: In real Verifone data from store 1320 (Nov 2025), ALL 200 sale transactions
      // contained line items. Pay-at-pump transactions DO have line items in Verifone XML.
      if (fuelAmount === 0 && merchAmount === 0 && subtotal > 0) {
        // FAIL-FAST: Throw error to abort parsing and alert operators
        // This prevents data corruption and forces investigation/enhancement
        throw new Error(
          `[Verifone CPJR] Cannot process transaction ${uniqueID}: has subtotal $${subtotal} but no line items. ` +
          `Cannot classify as fuel or merchandise without line item data. ` +
          `Parser enhancement required to extract fuel/merch data from trDispensers, trPaylines, or tender metadata. ` +
          `Transaction timestamp: ${transactionDateTime}`
        );
      }

      if (uniqueID) {
        transactions.push({
          transactionId: uniqueID,
          transactionDateTime,
          cashierId,
          fuelVolume,
          fuelAmount,
          merchAmount,
          totalAmount,
          tenderType,
        });
      }
    }

    return {
      transactions,
      lineItems,
      loyalty: [],
      summary: { voidCount, voidAmount, noSaleCount: 0 },
      dispensers: [],
    };
  } catch (error) {
    console.error('Error parsing Verifone CPJR XML:', error);
    throw new Error(`Failed to parse Verifone CPJR XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
