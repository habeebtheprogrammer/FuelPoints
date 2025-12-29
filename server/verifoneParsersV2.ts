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

type AnyRecord = Record<string, any>;
type NumericLike = string | number | null | undefined;

function getField(obj: AnyRecord, ...keys: string[]): unknown {
  if (!obj || typeof obj !== 'object') return undefined;
  for (const key of keys) {
    if (key in obj) {
      const val = obj[key];
      if (Array.isArray(val) && val.length > 0) {
        return val[0];
      }
      return val;
    }
  }
  return undefined;
}

function getStringField(obj: AnyRecord, ...keys: string[]): string {
  const raw = getField(obj, ...keys);
  if (raw === null || raw === undefined) return '';
  if (typeof raw === 'object') {
    const rawObj = raw as AnyRecord;
    if ('_' in rawObj) return String(rawObj._);
    if ('$' in rawObj && typeof rawObj.$ === 'object') {
      const attrs = rawObj.$ as AnyRecord;
      return String(attrs.name || attrs.value || '');
    }
  }
  return String(raw);
}

function getNumberField(obj: AnyRecord, ...keys: string[]): number {
  const raw = getField(obj, ...keys) as NumericLike;
  return toNumber(raw);
}

function toNumber(value: NumericLike): number {
  if (value === null || value === undefined || value === '') return 0;
  if (typeof value === 'number') return value;
  if (typeof value === 'object') {
    const objVal = value as any;
    if ('_' in objVal) value = objVal._;
    else return 0;
  }
  const cleaned = String(value).replace(/[^0-9.\-]/g, '');
  const n = parseFloat(cleaned);
  return Number.isNaN(n) ? 0 : n;
}

function getAttrField(obj: AnyRecord, attrName: string): string {
  if (!obj || typeof obj !== 'object') return '';
  if ('$' in obj && typeof obj.$ === 'object' && attrName in obj.$) {
    return String(obj.$[attrName]);
  }
  return '';
}

function safeArray(val: unknown): any[] {
  if (Array.isArray(val)) return val;
  if (val && typeof val === 'object') return [val];
  return [];
}

export async function parseVerifoneFGMv2(xmlContent: string, businessDate: string): Promise<FuelGradeData[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    const fuelTotals = result['fuel:fuelTotals'] || result['fuelTotals'];
    
    if (!fuelTotals) {
      console.warn('[V2 FGM] No fuel:fuelTotals root element found');
      return [];
    }

    const dispenserData = safeArray(fuelTotals.fpDispenserData);
    if (dispenserData.length === 0) {
      console.warn('[V2 FGM] No fpDispenserData found');
      return [];
    }

    const gradeMap = new Map<string, FuelGradeData>();

    for (const dispenser of dispenserData) {
      const productID = getStringField(dispenser, 'productID', 'ProductID', 'productId');
      const productNumberData = getField(dispenser, 'productNumber', 'ProductNumber');
      const productName = typeof productNumberData === 'object' 
        ? getAttrField(productNumberData, 'name') || getStringField(productNumberData as AnyRecord)
        : String(productNumberData || '');
      
      const volume = getNumberField(dispenser, 'fuelVolume', 'FuelVolume', 'volume', 'Volume');
      const amount = getNumberField(dispenser, 'fuelMoney', 'FuelMoney', 'amount', 'Amount');
      
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

    const results = Array.from(gradeMap.values());
    console.log(`[V2 FGM] Parsed ${results.length} fuel grades from ${dispenserData.length} dispensers`);
    return results;
  } catch (error) {
    console.error('[V2 FGM] Parse error:', error);
    throw new Error(`Failed to parse Verifone FGM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function parseVerifoneISMv2(xmlContent: string, businessDate: string): Promise<{ items: ItemSalesData[], departments: DepartmentData[] }> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    let productData: any[] = [];
    const allProdReport = result['merch:allProductReport'] || result['allProductReport'];
    if (allProdReport) {
      productData = safeArray(allProdReport.productData || allProdReport.ProductData);
    }

    const items: ItemSalesData[] = [];
    const departmentMap = new Map<string, DepartmentData>();

    for (const product of productData) {
      const upc = getStringField(product, 'upc', 'UPC', 'productNumber', 'ProductNumber', 'itemCode');
      const description = getStringField(product, 'productName', 'ProductName', 'description', 'Description', 'name');
      const departmentCode = getStringField(product, 'department', 'Department', 'categoryCode', 'CategoryCode', 'deptCode');
      const departmentName = getStringField(product, 'departmentName', 'DepartmentName', 'categoryName', 'CategoryName');
      
      const quantity = getNumberField(product, 'quantitySold', 'QuantitySold', 'quantity', 'Quantity', 'qty');
      const salesAmount = getNumberField(product, 'salesAmount', 'SalesAmount', 'totalSales', 'TotalSales', 'amount');

      if (upc && quantity > 0) {
        items.push({
          upc,
          description: description || 'Unknown',
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
            departmentName: departmentName || 'Miscellaneous',
            salesAmount,
            quantity,
            transactionCount: 1,
          });
        }
      }
    }

    console.log(`[V2 ISM] Parsed ${items.length} items, ${departmentMap.size} departments`);
    return { items, departments: Array.from(departmentMap.values()) };
  } catch (error) {
    console.error('[V2 ISM] Parse error:', error);
    throw new Error(`Failed to parse Verifone ISM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function parseVerifoneMCMv2(xmlContent: string, businessDate: string): Promise<DepartmentData[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    let categoryData: any[] = [];
    const catReport = result['merch:categoryReport'] || result['categoryReport'];
    if (catReport) {
      categoryData = safeArray(catReport.categoryData || catReport.CategoryData);
    }

    const departments: DepartmentData[] = [];

    for (const category of categoryData) {
      const departmentCode = getStringField(category, 'categoryCode', 'CategoryCode', 'departmentCode', 'DepartmentCode', 'code');
      const departmentName = getStringField(category, 'categoryName', 'CategoryName', 'departmentName', 'DepartmentName', 'name');
      const salesAmount = getNumberField(category, 'salesAmount', 'SalesAmount', 'totalSales', 'TotalSales', 'amount');
      const quantity = getNumberField(category, 'quantitySold', 'QuantitySold', 'quantity', 'Quantity', 'qty');
      const transactionCount = Math.floor(getNumberField(category, 'transactionCount', 'TransactionCount', 'txnCount', 'count'));

      if (departmentCode) {
        departments.push({
          departmentCode,
          departmentName: departmentName || 'Unknown',
          salesAmount,
          quantity,
          transactionCount,
        });
      }
    }

    console.log(`[V2 MCM] Parsed ${departments.length} departments`);
    return departments;
  } catch (error) {
    console.error('[V2 MCM] Parse error:', error);
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

export async function parseVerifoneCPJRv2(xmlContent: string, businessDate: string): Promise<CPJRData> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    const transSet = result['transSet'] || result['TransSet'];
    if (!transSet) {
      console.warn('[V2 CPJR] No transSet root element found');
      return { transactions: [], lineItems: [], loyalty: [], summary: {}, dispensers: [] };
    }

    const transactions: any[] = [];
    const lineItems: any[] = [];
    let voidCount = 0;
    let voidAmount = 0;
    
    const transData = safeArray(transSet.trans || transSet.Trans);
    const transactionMap = new Map<string, any>();

    for (const trans of transData) {
      const transType = getAttrField(trans, 'type');
      
      if (transType !== 'sale' && transType !== 'network sale') {
        if (transType === 'void') {
          const trValue = getField(trans, 'trValue', 'TrValue') as AnyRecord;
          const voidTotal = getNumberField(trValue || {}, 'trCurrTot', 'trTotWTax', 'total');
          voidCount++;
          voidAmount += voidTotal;
        }
        continue;
      }
      
      const trHeader = getField(trans, 'trHeader', 'TrHeader') as AnyRecord;
      const uniqueID = getStringField(trHeader || {}, 'uniqueID', 'UniqueID', 'trUniqueSN', 'TrUniqueSN');
      
      if (!uniqueID) continue;
      
      if (!transactionMap.has(uniqueID)) {
        transactionMap.set(uniqueID, trans);
      } else {
        const existingTrans = transactionMap.get(uniqueID);
        const existingTrLines = getField(existingTrans, 'trLines', 'TrLines') as AnyRecord;
        const newTrLines = getField(trans, 'trLines', 'TrLines') as AnyRecord;
        
        const existingLines = safeArray(existingTrLines?.trLine || existingTrLines?.TrLine);
        const newLines = safeArray(newTrLines?.trLine || newTrLines?.TrLine);
        
        if (newLines.length > 0) {
          if (!existingTrans.trLines) {
            existingTrans.trLines = [{ trLine: [] }];
          }
          existingTrans.trLines[0].trLine = [...existingLines, ...newLines];
        }
      }
    }
    
    for (const [uniqueID, trans] of transactionMap.entries()) {
      const trHeader = getField(trans, 'trHeader', 'TrHeader') as AnyRecord;
      const trValue = getField(trans, 'trValue', 'TrValue') as AnyRecord;
      const trLines = getField(trans, 'trLines', 'TrLines') as AnyRecord;
      const trPaylines = getField(trans, 'trPaylines', 'TrPaylines') as AnyRecord;

      if (!trHeader || !trValue) continue;

      const trTickNum = getField(trHeader, 'trTickNum', 'TrTickNum') as AnyRecord;
      const registerNumber = getStringField(trTickNum || {}, 'posNum', 'PosNum') || getStringField(trHeader, 'posNum', 'PosNum') || '0';
      const transactionDateTime = getStringField(trHeader, 'date', 'Date', 'dateTime', 'DateTime') || new Date().toISOString();
      const cashierData = getField(trHeader, 'cashier', 'Cashier');
      const cashierId = (typeof cashierData === 'object' ? getAttrField(cashierData as AnyRecord, 'sysid') : '') || registerNumber;

      const totalAmount = getNumberField(trValue, 'trTotWTax', 'TrTotWTax', 'trCurrTot', 'TrCurrTot', 'total');
      const subtotal = getNumberField(trValue, 'trTotNoTax', 'TrTotNoTax', 'subtotal');
      const taxAmount = getNumberField(trValue, 'trTotTax', 'TrTotTax', 'tax');

      let tenderType = 'UNKNOWN';
      const paylineData = safeArray(trPaylines?.trPayline || trPaylines?.TrPayline);
      if (paylineData.length > 0) {
        const payline = paylineData[0];
        const paycode = getField(payline, 'trpPaycode', 'TrpPaycode');
        if (typeof paycode === 'string') {
          tenderType = paycode;
        } else if (typeof paycode === 'object') {
          tenderType = getAttrField(paycode as AnyRecord, 'mop') || (paycode as any)._ || 'UNKNOWN';
        }
      }

      let fuelAmount = 0;
      let merchAmount = 0;
      let fuelVolume = 0;

      const lineData = safeArray(trLines?.trLine || trLines?.TrLine);
      for (const line of lineData) {
        const lineType = getAttrField(line, 'type');
        const upc = getStringField(line, 'trlUPC', 'TrlUPC', 'upc', 'UPC');
        const description = getStringField(line, 'trlDesc', 'TrlDesc', 'description', 'Description');
        const quantity = getNumberField(line, 'trlQty', 'TrlQty', 'quantity', 'Quantity') || 1;
        const lineTotal = getNumberField(line, 'trlLineTot', 'TrlLineTot', 'lineTot', 'LineTot', 'amount');
        const deptInfo = getField(line, 'trlDept', 'TrlDept') as AnyRecord;
        const departmentCode = typeof deptInfo === 'object' ? getAttrField(deptInfo, 'number') : '';
        
        const isFuel = lineType === 'fuel' || (departmentCode && parseInt(departmentCode) >= 10 && parseInt(departmentCode) <= 19);
        
        if (isFuel) {
          fuelAmount += lineTotal;
          fuelVolume += quantity;
        } else {
          merchAmount += lineTotal;
        }

        lineItems.push({
          posTransactionId: uniqueID,
          itemType: isFuel ? 'fuel' : 'merchandise',
          upc: upc || null,
          description: description || null,
          pumpNumber: isFuel ? departmentCode : null,
          quantity,
          amount: lineTotal,
        });
      }

      if (fuelAmount === 0 && merchAmount === 0 && subtotal > 0) {
        console.warn(`[V2 CPJR] Transaction ${uniqueID} has subtotal $${subtotal} but no classifiable line items - classifying as merchandise`);
        merchAmount = subtotal;
      }

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

    console.log(`[V2 CPJR] Parsed ${transactions.length} transactions, ${lineItems.length} line items`);
    
    return {
      transactions,
      lineItems,
      loyalty: [],
      summary: { voidCount, voidAmount, noSaleCount: 0 },
      dispensers: [],
    };
  } catch (error) {
    console.error('[V2 CPJR] Parse error:', error);
    throw new Error(`Failed to parse Verifone CPJR XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
