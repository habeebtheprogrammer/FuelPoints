import { parseStringPromise } from 'xml2js';
import { parseVerifoneDepartmentsFromCPJR, aggregateByDepartment, type VerifoneDepartment } from './verifoneDepartmentParser';
import { parseVerifoneFuelGradesFromCPJR, type VerifoneFuelGrade } from './verifoneFuelGradeParser';

export interface VerifoneStoreDayTotals {
  businessDate: string;
  pdiStoreNumber: string;
  fuelSales: {
    totalVolume: number;
    totalAmount: number;
    grades: VerifoneFuelGrade[];
  };
  merchandiseSales: {
    totalAmount: number;
    totalItems: number;
    departments: VerifoneDepartment[];
    departmentsByNacs: VerifoneDepartment[];
  };
  grandTotal: number;
  transactionCount: number;
  parseTimestamp: string;
}

export interface FGMCumulativeReading {
  gradeCode: string;
  gradeName: string;
  cumulativeVolume: number;
  cumulativeAmount: number;
  dispenserId: string;
  timestamp: string;
}

export interface FGMDailyCalculation {
  businessDate: string;
  pdiStoreNumber: string;
  grades: {
    gradeCode: string;
    gradeName: string;
    openingVolume: number;
    closingVolume: number;
    dailyVolume: number;
    openingAmount: number;
    closingAmount: number;
    dailyAmount: number;
    averagePrice: number;
  }[];
  totalDailyVolume: number;
  totalDailyAmount: number;
  calculatedFrom: 'differencing' | 'single_reading';
}

const VERIFONE_FUEL_GRADE_NAMES: Record<string, string> = {
  '1': 'Regular Unleaded',
  '2': 'Plus/Mid-Grade',
  '3': 'Premium',
  '4': 'Super Premium',
  '5': 'E85',
  '6': 'Bio Diesel',
  '7': 'Diesel #2',
  '8': 'Kerosene',
  '9': 'Kerosene',
  '19': 'Diesel',
  '9001': 'Regular Unleaded',
  '9002': 'Plus Unleaded',
  '9003': 'Premium Unleaded',
  '9004': 'Ultra Premium',
  '9005': 'Diesel',
  '9006': 'Kerosene',
  '9007': 'E85',
  '9008': 'DEF',
  '9009': 'Diesel #2',
  '9010': 'Bio Diesel',
  '9999': 'Fuel Deposit',
};

function getFuelGradeName(code: string): string {
  return VERIFONE_FUEL_GRADE_NAMES[code] || `Grade ${code}`;
}

export async function parseVerifoneFGMCumulative(
  xmlContent: string,
  pdiStoreNumber: string
): Promise<FGMCumulativeReading[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    const fuelTotals = result['fuel:fuelTotals'] || result['fuelTotals'];
    if (!fuelTotals) {
      console.warn('[Verifone FGM Parser] No fuelTotals root element found');
      return [];
    }

    const readings: FGMCumulativeReading[] = [];
    const dispenserData = fuelTotals.fpDispenserData || [];
    const timestamp = new Date().toISOString();

    for (const dispenser of dispenserData) {
      const dispenserId = dispenser.$?.id || dispenser.dispenserId?.[0] || '0';
      const productID = dispenser.productID?.[0] || '';
      const productNumberData = dispenser.productNumber?.[0];
      const productName = typeof productNumberData === 'object' 
        ? productNumberData.$.name 
        : productNumberData;
      
      const volumeData = dispenser.fuelVolume?.[0];
      const amountData = dispenser.fuelMoney?.[0];
      
      const volume = parseFloat(
        typeof volumeData === 'object' ? volumeData._ || '0' : volumeData || '0'
      );
      const amount = parseFloat(
        typeof amountData === 'object' ? amountData._ || '0' : amountData || '0'
      );
      
      if (!productID) continue;

      readings.push({
        gradeCode: productID,
        gradeName: getFuelGradeName(productID) || productName || `Grade ${productID}`,
        cumulativeVolume: volume,
        cumulativeAmount: amount,
        dispenserId,
        timestamp
      });
    }

    console.log(`[Verifone FGM Parser] Parsed ${readings.length} cumulative readings for store ${pdiStoreNumber}`);
    return readings;
  } catch (error) {
    console.error('[Verifone FGM Parser] Parse error:', error);
    throw new Error(`Failed to parse Verifone FGM data: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export function calculateDailyFuelFromCumulativeReadings(
  openingReadings: FGMCumulativeReading[],
  closingReadings: FGMCumulativeReading[],
  businessDate: string,
  pdiStoreNumber: string
): FGMDailyCalculation {
  const gradeMap = new Map<string, {
    gradeCode: string;
    gradeName: string;
    openingVolume: number;
    closingVolume: number;
    openingAmount: number;
    closingAmount: number;
  }>();

  for (const reading of openingReadings) {
    const key = `${reading.dispenserId}-${reading.gradeCode}`;
    gradeMap.set(key, {
      gradeCode: reading.gradeCode,
      gradeName: reading.gradeName,
      openingVolume: reading.cumulativeVolume,
      closingVolume: 0,
      openingAmount: reading.cumulativeAmount,
      closingAmount: 0
    });
  }

  for (const reading of closingReadings) {
    const key = `${reading.dispenserId}-${reading.gradeCode}`;
    if (gradeMap.has(key)) {
      const existing = gradeMap.get(key)!;
      existing.closingVolume = reading.cumulativeVolume;
      existing.closingAmount = reading.cumulativeAmount;
    } else {
      gradeMap.set(key, {
        gradeCode: reading.gradeCode,
        gradeName: reading.gradeName,
        openingVolume: 0,
        closingVolume: reading.cumulativeVolume,
        openingAmount: 0,
        closingAmount: reading.cumulativeAmount
      });
    }
  }

  const aggregatedGrades = new Map<string, {
    gradeCode: string;
    gradeName: string;
    openingVolume: number;
    closingVolume: number;
    dailyVolume: number;
    openingAmount: number;
    closingAmount: number;
    dailyAmount: number;
  }>();

  for (const [, data] of gradeMap) {
    const dailyVolume = data.closingVolume - data.openingVolume;
    const dailyAmount = data.closingAmount - data.openingAmount;

    if (aggregatedGrades.has(data.gradeCode)) {
      const existing = aggregatedGrades.get(data.gradeCode)!;
      existing.openingVolume += data.openingVolume;
      existing.closingVolume += data.closingVolume;
      existing.dailyVolume += dailyVolume;
      existing.openingAmount += data.openingAmount;
      existing.closingAmount += data.closingAmount;
      existing.dailyAmount += dailyAmount;
    } else {
      aggregatedGrades.set(data.gradeCode, {
        gradeCode: data.gradeCode,
        gradeName: data.gradeName,
        openingVolume: data.openingVolume,
        closingVolume: data.closingVolume,
        dailyVolume,
        openingAmount: data.openingAmount,
        closingAmount: data.closingAmount,
        dailyAmount
      });
    }
  }

  const grades = Array.from(aggregatedGrades.values()).map(g => ({
    ...g,
    averagePrice: g.dailyVolume > 0 ? g.dailyAmount / g.dailyVolume : 0
  }));

  const totalDailyVolume = grades.reduce((sum, g) => sum + g.dailyVolume, 0);
  const totalDailyAmount = grades.reduce((sum, g) => sum + g.dailyAmount, 0);

  console.log(`[Verifone FGM Differencing] Store ${pdiStoreNumber} Date ${businessDate}:`);
  console.log(`  Total daily volume: ${totalDailyVolume.toFixed(3)} gallons`);
  console.log(`  Total daily amount: $${totalDailyAmount.toFixed(2)}`);
  for (const g of grades) {
    console.log(`  ${g.gradeName}: ${g.dailyVolume.toFixed(3)} gal @ avg $${g.averagePrice.toFixed(3)}/gal = $${g.dailyAmount.toFixed(2)}`);
  }

  return {
    businessDate,
    pdiStoreNumber,
    grades,
    totalDailyVolume,
    totalDailyAmount,
    calculatedFrom: 'differencing'
  };
}

export async function parseVerifoneStoreDayFromCPJR(
  cpjrXmlContent: string,
  businessDate: string,
  pdiStoreNumber: string
): Promise<VerifoneStoreDayTotals> {
  console.log(`[Final Verifone Parser] Processing store ${pdiStoreNumber} for ${businessDate}`);

  const fuelResult = await parseVerifoneFuelGradesFromCPJR(cpjrXmlContent, businessDate);
  
  const fuelGradesFiltered = fuelResult.fuelGrades.filter(g => g.gradeCode !== '9999');
  const fuelDeposit = fuelResult.fuelGrades.find(g => g.gradeCode === '9999');
  
  const fuelTotalAmount = fuelGradesFiltered.reduce((sum, g) => sum + g.salesAmount, 0);
  const fuelTotalVolume = fuelGradesFiltered.reduce((sum, g) => sum + g.volume, 0);

  if (fuelDeposit) {
    console.log(`[Final Verifone Parser] Excluded fuel deposit (9999): $${fuelDeposit.salesAmount.toFixed(2)}`);
  }

  const deptResult = await parseVerifoneDepartmentsFromCPJR(cpjrXmlContent, businessDate);
  const departmentsByNacs = aggregateByDepartment(deptResult.departments);
  
  const merchTotalAmount = deptResult.summary.totalSalesAmount;
  const merchTotalItems = deptResult.summary.totalItems;

  const grandTotal = fuelTotalAmount + merchTotalAmount;
  const transactionCount = fuelResult.summary.totalTransactions + 
    deptResult.departments.reduce((sum, d) => sum + d.transactionCount, 0);

  console.log(`[Final Verifone Parser] Summary for ${pdiStoreNumber} on ${businessDate}:`);
  console.log(`  Fuel: ${fuelTotalVolume.toFixed(3)} gal = $${fuelTotalAmount.toFixed(2)}`);
  console.log(`  Merchandise: ${merchTotalItems} items = $${merchTotalAmount.toFixed(2)}`);
  console.log(`  Grand Total: $${grandTotal.toFixed(2)}`);

  return {
    businessDate,
    pdiStoreNumber,
    fuelSales: {
      totalVolume: fuelTotalVolume,
      totalAmount: fuelTotalAmount,
      grades: fuelGradesFiltered
    },
    merchandiseSales: {
      totalAmount: merchTotalAmount,
      totalItems: merchTotalItems,
      departments: deptResult.departments,
      departmentsByNacs
    },
    grandTotal,
    transactionCount,
    parseTimestamp: new Date().toISOString()
  };
}

export interface VerifoneFullDayReport {
  businessDate: string;
  pdiStoreNumber: string;
  posType: 'verifone';
  fuel: {
    totalVolume: number;
    totalAmount: number;
    grades: {
      gradeCode: string;
      gradeName: string;
      volume: number;
      amount: number;
      averagePrice: number;
      transactionCount: number;
    }[];
  };
  merchandise: {
    totalAmount: number;
    totalItems: number;
    categories: {
      categoryCode: string;
      categoryName: string;
      departmentCode: string;
      departmentName: string;
      salesAmount: number;
      quantity: number;
    }[];
    departments: {
      departmentCode: string;
      departmentName: string;
      salesAmount: number;
      quantity: number;
    }[];
  };
  transactions: {
    totalCount: number;
    fuelOnly: number;
    merchOnly: number;
    mixed: number;
  };
  totals: {
    grossSales: number;
    fuelSales: number;
    merchSales: number;
  };
  metadata: {
    parsedAt: string;
    dataSource: 'cpjr';
    parserVersion: '1.0.0';
  };
}

export async function generateVerifoneFullDayReport(
  cpjrXmlContent: string,
  businessDate: string,
  pdiStoreNumber: string
): Promise<VerifoneFullDayReport> {
  const storeDayTotals = await parseVerifoneStoreDayFromCPJR(cpjrXmlContent, businessDate, pdiStoreNumber);

  const fuelGrades = storeDayTotals.fuelSales.grades.map(g => ({
    gradeCode: g.gradeCode,
    gradeName: g.gradeName,
    volume: g.volume,
    amount: g.salesAmount,
    averagePrice: g.averagePrice,
    transactionCount: g.transactionCount
  }));

  const categories = storeDayTotals.merchandiseSales.departments.map(d => ({
    categoryCode: d.categoryCode,
    categoryName: d.categoryName,
    departmentCode: d.departmentCode,
    departmentName: d.departmentName,
    salesAmount: d.salesAmount,
    quantity: d.quantity
  }));

  const departments = storeDayTotals.merchandiseSales.departmentsByNacs.map(d => ({
    departmentCode: d.departmentCode,
    departmentName: d.departmentName,
    salesAmount: d.salesAmount,
    quantity: d.quantity
  }));

  return {
    businessDate,
    pdiStoreNumber,
    posType: 'verifone',
    fuel: {
      totalVolume: storeDayTotals.fuelSales.totalVolume,
      totalAmount: storeDayTotals.fuelSales.totalAmount,
      grades: fuelGrades
    },
    merchandise: {
      totalAmount: storeDayTotals.merchandiseSales.totalAmount,
      totalItems: storeDayTotals.merchandiseSales.totalItems,
      categories,
      departments
    },
    transactions: {
      totalCount: storeDayTotals.transactionCount,
      fuelOnly: 0,
      merchOnly: 0,
      mixed: 0
    },
    totals: {
      grossSales: storeDayTotals.grandTotal,
      fuelSales: storeDayTotals.fuelSales.totalAmount,
      merchSales: storeDayTotals.merchandiseSales.totalAmount
    },
    metadata: {
      parsedAt: new Date().toISOString(),
      dataSource: 'cpjr',
      parserVersion: '1.0.0'
    }
  };
}

export async function parseVerifoneTransactionJournal(
  cpjrXmlContent: string,
  businessDate: string
): Promise<{
  transactions: {
    transactionId: string;
    timestamp: string;
    type: 'fuel' | 'merchandise' | 'mixed';
    fuelAmount: number;
    fuelVolume: number;
    merchAmount: number;
    totalAmount: number;
    tenderType: string;
    lineItems: {
      type: 'fuel' | 'merchandise';
      upc: string | null;
      description: string;
      quantity: number;
      amount: number;
      departmentCode: string;
    }[];
  }[];
  summary: {
    totalTransactions: number;
    fuelTransactions: number;
    merchTransactions: number;
    mixedTransactions: number;
    totalFuelAmount: number;
    totalFuelVolume: number;
    totalMerchAmount: number;
    totalAmount: number;
    voidCount: number;
    voidAmount: number;
  };
}> {
  const result = await parseStringPromise(cpjrXmlContent);
  
  const transSet = result['transSet'] || result['TransSet'];
  if (!transSet) {
    return {
      transactions: [],
      summary: {
        totalTransactions: 0,
        fuelTransactions: 0,
        merchTransactions: 0,
        mixedTransactions: 0,
        totalFuelAmount: 0,
        totalFuelVolume: 0,
        totalMerchAmount: 0,
        totalAmount: 0,
        voidCount: 0,
        voidAmount: 0
      }
    };
  }

  const transactions: any[] = [];
  const transData = transSet.trans || transSet.Trans || [];
  
  let voidCount = 0;
  let voidAmount = 0;
  let fuelTransactions = 0;
  let merchTransactions = 0;
  let mixedTransactions = 0;
  let totalFuelAmount = 0;
  let totalFuelVolume = 0;
  let totalMerchAmount = 0;

  const transactionMap = new Map<string, any>();

  for (const trans of transData) {
    const transType = trans.$?.type || trans.$?.Type || '';
    
    if (transType === 'void') {
      const trValue = trans.trValue?.[0];
      const amount = parseFloat(trValue?.trCurrTot?.[0] || trValue?.trTotWTax?.[0] || '0');
      voidCount++;
      voidAmount += amount;
      continue;
    }
    
    if (transType !== 'sale' && transType !== 'network sale') {
      continue;
    }
    
    const trHeader = trans.trHeader?.[0];
    const uniqueID = trHeader?.uniqueID?.[0] || trHeader?.trUniqueSN?.[0] || '';
    
    if (!uniqueID) continue;
    
    if (!transactionMap.has(uniqueID)) {
      transactionMap.set(uniqueID, trans);
    } else {
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

  for (const [uniqueID, trans] of transactionMap.entries()) {
    const trHeader = trans.trHeader?.[0];
    const trValue = trans.trValue?.[0];
    const trLines = trans.trLines?.[0];
    const trPaylines = trans.trPaylines?.[0];

    if (!trHeader || !trValue) continue;

    const timestamp = trHeader.date?.[0] || new Date().toISOString();
    const totalAmount = parseFloat(trValue.trTotWTax?.[0] || trValue.trCurrTot?.[0] || '0');

    let tenderType = 'UNKNOWN';
    if (trPaylines?.trPayline) {
      const payline = trPaylines.trPayline[0];
      const paycode = payline.trpPaycode?.[0];
      tenderType = typeof paycode === 'string' ? paycode : (paycode?._ || paycode?.$?.mop || 'UNKNOWN');
    }

    let fuelAmount = 0;
    let fuelVolume = 0;
    let merchAmount = 0;
    const lineItems: any[] = [];

    if (trLines?.trLine) {
      for (const line of trLines.trLine) {
        const deptInfo = line.trlDept?.[0] || line.TrlDept?.[0];
        const deptCode = typeof deptInfo === 'object' 
          ? (deptInfo.$?.number || deptInfo.$?.Number || '')
          : '';
        const deptType = typeof deptInfo === 'object'
          ? (deptInfo.$?.type || deptInfo.$?.Type || '')
          : '';
        
        const deptCodeNum = parseInt(deptCode);
        const isFuel = deptType.toLowerCase() === 'fuel' || 
                       (deptCodeNum >= 9000 && deptCodeNum <= 9999);

        const upc = line.trlUPC?.[0] || null;
        const description = line.trlDesc?.[0] || (typeof deptInfo === 'object' ? deptInfo._ : '') || '';
        const quantity = parseFloat(line.trlQty?.[0] || line.TrlQty?.[0] || '1');
        const amount = parseFloat(line.trlLineTot?.[0] || line.TrlLineTot?.[0] || '0');

        if (isFuel) {
          fuelAmount += amount;
          fuelVolume += quantity;
        } else {
          merchAmount += amount;
        }

        lineItems.push({
          type: isFuel ? 'fuel' : 'merchandise',
          upc,
          description,
          quantity,
          amount,
          departmentCode: deptCode
        });
      }
    }

    let transType: 'fuel' | 'merchandise' | 'mixed';
    if (fuelAmount > 0 && merchAmount > 0) {
      transType = 'mixed';
      mixedTransactions++;
    } else if (fuelAmount > 0) {
      transType = 'fuel';
      fuelTransactions++;
    } else {
      transType = 'merchandise';
      merchTransactions++;
    }

    totalFuelAmount += fuelAmount;
    totalFuelVolume += fuelVolume;
    totalMerchAmount += merchAmount;

    transactions.push({
      transactionId: uniqueID,
      timestamp,
      type: transType,
      fuelAmount,
      fuelVolume,
      merchAmount,
      totalAmount,
      tenderType,
      lineItems
    });
  }

  return {
    transactions,
    summary: {
      totalTransactions: transactions.length,
      fuelTransactions,
      merchTransactions,
      mixedTransactions,
      totalFuelAmount,
      totalFuelVolume,
      totalMerchAmount,
      totalAmount: totalFuelAmount + totalMerchAmount,
      voidCount,
      voidAmount
    }
  };
}
