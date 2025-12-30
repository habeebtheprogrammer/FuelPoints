import { parseStringPromise } from 'xml2js';

export interface VerifoneDepartment {
  categoryCode: string;
  categoryName: string;
  departmentCode: string;
  departmentName: string;
  salesAmount: number;
  quantity: number;
  transactionCount: number;
}

export interface VerifoneDepartmentParseResult {
  departments: VerifoneDepartment[];
  summary: {
    totalCategories: number;
    totalDepartments: number;
    totalSalesAmount: number;
    totalItems: number;
  };
}

const CATEGORY_TO_DEPARTMENT_MAP: Record<string, { deptCode: string; deptName: string; catName: string }> = {
  '2':   { deptCode: '101', deptName: '101 Cigarettes', catName: '02 Cigarettes' },
  '3':   { deptCode: '102', deptName: '102 Other Tobacco', catName: '03 Other Tobacco' },
  '4':   { deptCode: '103', deptName: '103 Alcoholic Beverages', catName: '04 Beer' },
  '5':   { deptCode: '103', deptName: '103 Alcoholic Beverages', catName: '05 Wine' },
  '6':   { deptCode: '103', deptName: '103 Alcoholic Beverages', catName: '06 Liquor' },
  '7':   { deptCode: '104', deptName: '104 Packaged Beverages', catName: '07 Package Bev (non Alch)' },
  '8':   { deptCode: '105', deptName: '105 Candy', catName: '08 Candy' },
  '9':   { deptCode: '106', deptName: '106 Dairy', catName: '09 Fluid Milk Products' },
  '10':  { deptCode: '106', deptName: '106 Dairy', catName: '10 Other Dairy And Deli' },
  '11':  { deptCode: '107', deptName: '107 Packaged Commissary', catName: '11 Commissary & Oth Pkg Prods' },
  '12':  { deptCode: '108', deptName: '108 Ice Cream', catName: '12 Pkg Ice Cream/novelities' },
  '13':  { deptCode: '110', deptName: '110 Grocery', catName: '13 Frozen Foods' },
  '14':  { deptCode: '110', deptName: '110 Grocery', catName: '14 Packaged Bread' },
  '15':  { deptCode: '109', deptName: '109 Snacks', catName: '15 Salty Snacks' },
  '16':  { deptCode: '109', deptName: '109 Snacks', catName: '16 Packaged Sweet Snacks' },
  '17':  { deptCode: '109', deptName: '109 Snacks', catName: '17 Alternative Snacks' },
  '18':  { deptCode: '107', deptName: '107 Packaged Commissary', catName: '18 Perishable Grocery' },
  '19':  { deptCode: '110', deptName: '110 Grocery', catName: '19 Edible Grocery' },
  '20':  { deptCode: '110', deptName: '110 Grocery', catName: '20 Non Edible Grocery' },
  '21':  { deptCode: '112', deptName: '112 General Merchandise', catName: '21 Health & Beauty Care' },
  '22':  { deptCode: '112', deptName: '112 General Merchandise', catName: '22 General Merchandise' },
  '23':  { deptCode: '112', deptName: '112 General Merchandise', catName: '23 Publications' },
  '24':  { deptCode: '112', deptName: '112 General Merchandise', catName: '24 Automotive Products' },
  '25':  { deptCode: '900', deptName: '900 Expense', catName: '25 Automotive Services' },
  '26':  { deptCode: '900', deptName: '900 Expense', catName: '26 Store Services (fee-based)' },
  '27':  { deptCode: '114', deptName: '114 Scratch Lottery', catName: '27 Scratch Lottery' },
  '28':  { deptCode: '110', deptName: '110 Grocery', catName: '28 Ice' },
  '29':  { deptCode: '201', deptName: '201 Foodservice', catName: '29 Foodservice Prep On-site' },
  '30':  { deptCode: '202', deptName: '202 Hot Dispensed Beverages', catName: '30 Hot Dispensed Beverages' },
  '31':  { deptCode: '203', deptName: '203 Cold Dispensed Beverages', catName: '31 Cold Dispensed Beverages' },
  '32':  { deptCode: '203', deptName: '203 Cold Dispensed Beverages', catName: '32 Frozen Dispensed Beverages' },
  '33':  { deptCode: '112', deptName: '112 General Merchandise', catName: '33 Pre-paid Cards' },
  '60':  { deptCode: '102', deptName: '102 Other Tobacco', catName: '60 JUUL Devices' },
  '61':  { deptCode: '102', deptName: '102 Other Tobacco', catName: '61 JUUL Pods' },
  '90':  { deptCode: '900', deptName: '900 Expense', catName: '90 Online Lotto' },
  '91':  { deptCode: '900', deptName: '900 Expense', catName: '91 Lottery Vending' },
  '92':  { deptCode: '900', deptName: '900 Expense', catName: '92 Lotto Payouts' },
  '93':  { deptCode: '900', deptName: '900 Expense', catName: '93 Scratch Payout' },
  '94':  { deptCode: '900', deptName: '900 Expense', catName: '94 Mobile Coupons' },
  '97':  { deptCode: '900', deptName: '900 Expense', catName: '97 Tax Charges' },
  '98':  { deptCode: '900', deptName: '900 Expense', catName: '98 Invoice Fees' },
  '99':  { deptCode: '900', deptName: '900 Expense', catName: '99 Expense' },
  '501': { deptCode: '500', deptName: '500 Scan Based Trading', catName: '501 General Merch SBT' },
};

function isFuelCategory(code: string): boolean {
  const codeNum = parseInt(code);
  return codeNum >= 9000 && codeNum <= 9999;
}

function getMappedDepartment(categoryCode: string, rawCategoryName: string): { deptCode: string; deptName: string; catName: string } | null {
  if (isFuelCategory(categoryCode)) {
    return null;
  }
  
  const mapping = CATEGORY_TO_DEPARTMENT_MAP[categoryCode];
  if (mapping) {
    return mapping;
  }
  
  return {
    deptCode: '999',
    deptName: '999 Unmapped',
    catName: rawCategoryName || `Category ${categoryCode}`
  };
}

/**
 * Parse Verifone CPJR (Transaction Journal) XML to extract department sales data.
 * Maps product categories to standard department codes using NACS mapping.
 * Filters out fuel grades (9000+ codes).
 */
export async function parseVerifoneDepartmentsFromCPJR(
  xmlContent: string,
  businessDate: string
): Promise<VerifoneDepartmentParseResult> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    const transSet = result['transSet'] || result['TransSet'];
    if (!transSet) {
      console.warn('[Verifone Dept Parser] No transSet root element found');
      return {
        departments: [],
        summary: { totalCategories: 0, totalDepartments: 0, totalSalesAmount: 0, totalItems: 0 }
      };
    }

    const categoryMap = new Map<string, {
      categoryCode: string;
      categoryName: string;
      departmentCode: string;
      departmentName: string;
      salesAmount: number;
      quantity: number;
      transactionCount: number;
    }>();
    
    const transData = transSet.trans || transSet.Trans || [];
    let processedTransactions = 0;
    let skippedFuelItems = 0;

    for (const trans of transData) {
      const transType = trans.$?.type || trans.$?.Type || '';
      
      if (transType !== 'sale' && transType !== 'network sale') {
        continue;
      }
      
      processedTransactions++;
      
      const trLines = trans.trLines?.[0] || trans.TrLines?.[0];
      if (!trLines) continue;
      
      const lineItems = trLines.trLine || trLines.TrLine || [];
      
      for (const line of lineItems) {
        const deptInfo = line.trlDept?.[0] || line.TrlDept?.[0];
        if (!deptInfo) continue;
        
        const rawCatCode = typeof deptInfo === 'object' 
          ? (deptInfo.$?.number || deptInfo.$?.Number || 'UNKNOWN')
          : 'UNKNOWN';
        
        let rawCatName = '';
        if (typeof deptInfo === 'string') {
          rawCatName = deptInfo;
        } else if (typeof deptInfo === 'object') {
          rawCatName = deptInfo._ || deptInfo.$?.type || deptInfo.$?.Type || `Category ${rawCatCode}`;
        }
        
        const mapping = getMappedDepartment(rawCatCode, rawCatName);
        if (!mapping) {
          skippedFuelItems++;
          continue;
        }
        
        const lineTotal = parseFloat(
          line.trlLineTot?.[0] || line.TrlLineTot?.[0] || 
          line.trlAmount?.[0] || line.TrlAmount?.[0] || '0'
        );
        
        const quantity = parseFloat(
          line.trlQty?.[0] || line.TrlQty?.[0] || '1'
        );
        
        const key = rawCatCode;
        
        if (categoryMap.has(key)) {
          const existing = categoryMap.get(key)!;
          existing.salesAmount += lineTotal;
          existing.quantity += quantity;
          existing.transactionCount += 1;
        } else {
          categoryMap.set(key, {
            categoryCode: rawCatCode,
            categoryName: mapping.catName,
            departmentCode: mapping.deptCode,
            departmentName: mapping.deptName,
            salesAmount: lineTotal,
            quantity: quantity,
            transactionCount: 1
          });
        }
      }
    }

    const departments = Array.from(categoryMap.values());
    
    const uniqueDepts = new Set(departments.map(d => d.departmentCode));
    
    const summary = {
      totalCategories: departments.length,
      totalDepartments: uniqueDepts.size,
      totalSalesAmount: departments.reduce((sum, d) => sum + d.salesAmount, 0),
      totalItems: departments.reduce((sum, d) => sum + d.quantity, 0)
    };

    console.log(`[Verifone Dept Parser] Processed ${processedTransactions} transactions`);
    console.log(`[Verifone Dept Parser] Found ${departments.length} categories mapped to ${uniqueDepts.size} departments`);
    console.log(`[Verifone Dept Parser] Skipped ${skippedFuelItems} fuel items`);
    console.log(`[Verifone Dept Parser] Total merch sales: $${summary.totalSalesAmount.toFixed(2)}`);

    return { departments, summary };
  } catch (error) {
    console.log('[Verifone Dept Parser] Parse error:', error);
    throw new Error(`Failed to parse Verifone department data: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Aggregate departments by department code (not category code)
 * This combines categories that map to the same department
 */
export function aggregateByDepartment(departments: VerifoneDepartment[]): VerifoneDepartment[] {
  const deptMap = new Map<string, VerifoneDepartment>();
  
  for (const dept of departments) {
    const key = dept.departmentCode;
    
    if (deptMap.has(key)) {
      const existing = deptMap.get(key)!;
      existing.salesAmount += dept.salesAmount;
      existing.quantity += dept.quantity;
      existing.transactionCount += dept.transactionCount;
    } else {
      deptMap.set(key, {
        categoryCode: dept.departmentCode,
        categoryName: dept.departmentName,
        departmentCode: dept.departmentCode,
        departmentName: dept.departmentName,
        salesAmount: dept.salesAmount,
        quantity: dept.quantity,
        transactionCount: dept.transactionCount
      });
    }
  }
  
  return Array.from(deptMap.values()).sort((a, b) => b.salesAmount - a.salesAmount);
}
