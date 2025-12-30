import { parseStringPromise } from 'xml2js';

export interface VerifoneFuelGrade {
  gradeCode: string;
  gradeName: string;
  volume: number;
  salesAmount: number;
  transactionCount: number;
  averagePrice: number;
}

export interface VerifoneFuelGradeResult {
  fuelGrades: VerifoneFuelGrade[];
  summary: {
    totalGrades: number;
    totalVolume: number;
    totalSalesAmount: number;
    totalTransactions: number;
    averagePricePerGallon: number;
  };
}

const FUEL_GRADE_NAMES: Record<string, string> = {
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

function getFuelGradeName(code: string, rawName: string): string {
  return FUEL_GRADE_NAMES[code] || rawName || `Fuel Grade ${code}`;
}

/**
 * Parse Verifone CPJR (Transaction Journal) XML to extract fuel grade sales data.
 * Extracts volume and sales from fuel line items in transactions.
 */
export async function parseVerifoneFuelGradesFromCPJR(
  xmlContent: string,
  businessDate: string
): Promise<VerifoneFuelGradeResult> {
  try {
    const result = await parseStringPromise(xmlContent);
    
    const transSet = result['transSet'] || result['TransSet'];
    if (!transSet) {
      console.warn('[Verifone Fuel Parser] No transSet root element found');
      return {
        fuelGrades: [],
        summary: { totalGrades: 0, totalVolume: 0, totalSalesAmount: 0, totalTransactions: 0, averagePricePerGallon: 0 }
      };
    }

    const fuelGradeMap = new Map<string, VerifoneFuelGrade>();
    const transData = transSet.trans || transSet.Trans || [];
    let processedTransactions = 0;
    let fuelLineItems = 0;

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
        
        const deptCode = typeof deptInfo === 'object' 
          ? (deptInfo.$?.number || deptInfo.$?.Number || '')
          : '';
        
        const deptType = typeof deptInfo === 'object'
          ? (deptInfo.$?.type || deptInfo.$?.Type || '')
          : '';
        
        const deptCodeNum = parseInt(deptCode);
        const isFuel = deptType.toLowerCase() === 'fuel' || 
                       (deptCodeNum >= 9000 && deptCodeNum <= 9999);
        
        if (!isFuel) continue;
        
        fuelLineItems++;
        
        let rawGradeName = '';
        if (typeof deptInfo === 'string') {
          rawGradeName = deptInfo;
        } else if (typeof deptInfo === 'object') {
          rawGradeName = deptInfo._ || '';
        }
        
        const lineTotal = parseFloat(
          line.trlLineTot?.[0] || line.TrlLineTot?.[0] || '0'
        );
        
        // For fuel, quantity is the volume in gallons
        const volume = parseFloat(
          line.trlQty?.[0] || line.TrlQty?.[0] || '0'
        );
        
        // Check trlFuel element for accurate fuel volume
        const trlFuel = line.trlFuel?.[0] || line.TrlFuel?.[0];
        let fuelVolume = volume;
        
        if (trlFuel) {
          // Get volume from fuel-specific element (more accurate than trlQty)
          const fuelVolumeVal = trlFuel.fuelVolume?.[0] || trlFuel.FuelVolume?.[0];
          if (fuelVolumeVal) {
            fuelVolume = parseFloat(fuelVolumeVal);
          }
        }
        
        // Use trlDept number as the grade code (not fuelProd sysid)
        // trlDept number contains the actual fuel grade code (9001, 9002, 9004, 9005, etc.)
        const fuelGradeCode = deptCode;
        const gradeName = getFuelGradeName(fuelGradeCode, rawGradeName);
        
        if (fuelGradeMap.has(fuelGradeCode)) {
          const existing = fuelGradeMap.get(fuelGradeCode)!;
          existing.volume += fuelVolume;
          existing.salesAmount += lineTotal;
          existing.transactionCount += 1;
        } else {
          fuelGradeMap.set(fuelGradeCode, {
            gradeCode: fuelGradeCode,
            gradeName: gradeName,
            volume: fuelVolume,
            salesAmount: lineTotal,
            transactionCount: 1,
            averagePrice: 0
          });
        }
      }
    }

    // Calculate average price per gallon for each grade
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

    console.log(`[Verifone Fuel Parser] Processed ${processedTransactions} transactions, ${fuelLineItems} fuel items`);
    console.log(`[Verifone Fuel Parser] Found ${fuelGrades.length} fuel grades`);
    console.log(`[Verifone Fuel Parser] Total volume: ${totalVolume.toFixed(3)} gal, Sales: $${totalSalesAmount.toFixed(2)}`);

    return { fuelGrades, summary };
  } catch (error) {
    console.log('[Verifone Fuel Parser] Parse error:', error);
    throw new Error(`Failed to parse Verifone fuel grade data: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
