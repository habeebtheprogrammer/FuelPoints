import { parseStringPromise } from 'xml2js';

export interface FuelGradeData {
  gradeId: string;
  gradeName: string;
  volume: number;
  amount: number;
  discountAmount: number;
}

export interface ItemSalesData {
  upc: string;
  description: string;
  quantity: number;
  salesAmount: number;
}

export interface DepartmentData {
  departmentCode: string;
  departmentName: string;
  salesAmount: number;
  quantity: number;
  transactionCount: number;
}

const FUEL_GRADE_NAMES: Record<string, string> = {
  '001': 'Regular',
  '002': 'Plus/Mid-Grade',
  '003': 'Premium',
  '004': 'Super Premium',
  '019': 'Diesel',
  '005': 'E85',
};

export async function parseFGM(xmlContent: string, businessDate: string): Promise<FuelGradeData[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    const fgmRoot = result['NAXML-MovementReport'];
    
    if (!fgmRoot || !fgmRoot.FuelGradeMovement) {
      throw new Error('Invalid FGM XML structure');
    }

    const fgmDetails = fgmRoot.FuelGradeMovement[0].FGMDetail || [];
    
    const gradeMap = new Map<string, FuelGradeData>();

    for (const detail of fgmDetails) {
      const gradeId = detail.FuelGradeID?.[0] || '';
      
      if (!gradeId) continue;

      const tenderSummary = detail.FGMTenderSummary?.[0];
      if (!tenderSummary) continue;

      const sellPriceSummary = tenderSummary.FGMSellPriceSummary?.[0];
      if (!sellPriceSummary) continue;

      const serviceLevelSummary = sellPriceSummary.FGMServiceLevelSummary?.[0];
      if (!serviceLevelSummary) continue;

      const salesTotals = serviceLevelSummary.FGMSalesTotals?.[0];
      if (!salesTotals) continue;

      const volume = parseFloat(salesTotals.FuelGradeSalesVolume?.[0] || '0');
      const amount = parseFloat(salesTotals.FuelGradeSalesAmount?.[0] || '0');
      const discountAmount = parseFloat(salesTotals.DiscountAmount?.[0] || '0');

      if (gradeMap.has(gradeId)) {
        const existing = gradeMap.get(gradeId)!;
        existing.volume += volume;
        existing.amount += amount;
        existing.discountAmount += discountAmount;
      } else {
        gradeMap.set(gradeId, {
          gradeId,
          gradeName: FUEL_GRADE_NAMES[gradeId] || `Grade ${gradeId}`,
          volume,
          amount,
          discountAmount,
        });
      }
    }

    return Array.from(gradeMap.values());
  } catch (error) {
    console.log('Error parsing FGM XML:', error);
    throw new Error(`Failed to parse FGM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function parseISM(xmlContent: string, businessDate: string): Promise<{ items: ItemSalesData[], departments: DepartmentData[] }> {
  try {
    const result = await parseStringPromise(xmlContent);
    const ismRoot = result['NAXML-MovementReport'];
    
    if (!ismRoot || !ismRoot.ItemSalesMovement) {
      throw new Error('Invalid ISM XML structure');
    }

    const ismDetails = ismRoot.ItemSalesMovement[0].ISMDetail || [];
    
    const items: ItemSalesData[] = [];
    const departmentMap = new Map<string, DepartmentData>();

    for (const detail of ismDetails) {
      const itemCode = detail.ItemCode?.[0];
      const upc = itemCode?.POSCode?.[0] || '';
      const description = detail.Description?.[0] || '';
      const merchCode = detail.MerchandiseCode?.[0] || '';

      const sellPriceSummary = detail.ISMSellPriceSummary?.[0];
      if (!sellPriceSummary) continue;

      const salesTotals = sellPriceSummary.ISMSalesTotals?.[0];
      if (!salesTotals) continue;

      const quantity = parseFloat(salesTotals.SalesQuantity?.[0] || '0');
      const salesAmount = parseFloat(salesTotals.SalesAmount?.[0] || '0');
      const transactionCount = parseInt(salesTotals.TransactionCount?.[0] || '0', 10);

      if (upc && quantity > 0) {
        items.push({
          upc,
          description,
          quantity,
          salesAmount,
        });
      }

      if (merchCode) {
        if (departmentMap.has(merchCode)) {
          const existing = departmentMap.get(merchCode)!;
          existing.salesAmount += salesAmount;
          existing.quantity += quantity;
          existing.transactionCount += transactionCount;
        } else {
          departmentMap.set(merchCode, {
            departmentCode: merchCode,
            departmentName: `Department ${merchCode}`,
            salesAmount,
            quantity,
            transactionCount,
          });
        }
      }
    }

    return {
      items,
      departments: Array.from(departmentMap.values()),
    };
  } catch (error) {
    console.log('Error parsing ISM XML:', error);
    throw new Error(`Failed to parse ISM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function parseMCM(xmlContent: string, businessDate: string): Promise<DepartmentData[]> {
  try {
    const result = await parseStringPromise(xmlContent);
    const mcmRoot = result['NAXML-MovementReport'];
    
    if (!mcmRoot || !mcmRoot.MerchandiseCategoryMovement) {
      throw new Error('Invalid MCM XML structure');
    }

    const mcmDetails = mcmRoot.MerchandiseCategoryMovement[0].MCMDetail || [];
    
    const departments: DepartmentData[] = [];

    for (const detail of mcmDetails) {
      const merchCode = detail.MerchandiseCode?.[0] || '';
      const description = detail.Description?.[0] || '';

      const sellPriceSummary = detail.MCMSellPriceSummary?.[0];
      if (!sellPriceSummary) continue;

      const salesTotals = sellPriceSummary.MCMSalesTotals?.[0];
      if (!salesTotals) continue;

      const quantity = parseFloat(salesTotals.SalesQuantity?.[0] || '0');
      const salesAmount = parseFloat(salesTotals.SalesAmount?.[0] || '0');
      const transactionCount = parseInt(salesTotals.TransactionCount?.[0] || '0', 10);

      if (merchCode) {
        departments.push({
          departmentCode: merchCode,
          departmentName: description || `Department ${merchCode}`,
          salesAmount,
          quantity,
          transactionCount,
        });
      }
    }

    return departments;
  } catch (error) {
    console.log('Error parsing MCM XML:', error);
    throw new Error(`Failed to parse MCM XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export interface CPJRTransactionData {
  transactionId: string;
  transactionDateTime: string;
  cashierId: string | null;
  fuelVolume: number;
  fuelAmount: number;
  merchAmount: number;
  totalAmount: number;
  tenderType: string | null;
}

export interface CPJRLineItemData {
  posTransactionId: string;
  itemType: 'fuel' | 'merchandise';
  upc: string | null;
  description: string | null;
  pumpNumber: string | null;
  quantity: number;
  amount: number;
}

export interface CPJRLoyaltyData {
  posTransactionId: string;
  promotionId: string | null;
  promotionAmount: number;
}

export interface CPJRSummaryData {
  voidCount: number;
  voidAmount: number;
  noSaleCount: number;
}

export interface CPJRDispenserData {
  pumpNumber: string;
  count: number;
  amount: number;
  volume: number;
}

export interface CPJRData {
  transactions: CPJRTransactionData[];
  lineItems: CPJRLineItemData[];
  loyalty: CPJRLoyaltyData[];
  summary: CPJRSummaryData;
  dispensers: CPJRDispenserData[];
}

export async function parseCPJR(xmlContent: string, businessDate: string): Promise<CPJRData> {
  try {
    const result = await parseStringPromise(xmlContent);
    const journal = result['NAXML-POSJournal'];
    
    if (!journal || !journal.JournalReport || !journal.JournalReport[0]) {
      throw new Error('Invalid CPJR XML structure - expected NAXML-POSJournal format');
    }
    
    const root = journal.JournalReport[0];

    const transactions: CPJRTransactionData[] = [];
    const lineItems: CPJRLineItemData[] = [];
    const loyalty: CPJRLoyaltyData[] = [];
    const dispenserMap = new Map<string, CPJRDispenserData>();
    
    let voidCount = 0;
    let voidAmount = 0;
    let noSaleCount = 0;

    const saleEvents = root.SaleEvent || [];

    for (const saleEvent of saleEvents) {
      const transactionId = saleEvent.TransactionID?.[0] || '';
      const eventDate = saleEvent.EventStartDate?.[0] || '';
      const eventTime = saleEvent.EventStartTime?.[0] || '';
      const eventDateTime = eventDate && eventTime ? `${eventDate}T${eventTime}` : eventDate;
      const cashierId = saleEvent.CashierID?.[0] || null;

      let fuelVolume = 0;
      let fuelAmount = 0;
      let merchAmount = 0;
      let totalAmount = 0;
      let tenderType: string | null = null;

      const transactionDetailGroup = saleEvent.TransactionDetailGroup?.[0];
      const transactionLines = transactionDetailGroup?.TransactionLine || [];
      
      for (const transLine of transactionLines) {
        const lineStatus = transLine.$.status || 'normal';
        
        // Extract tender type from this line if present
        const tenderInfo = transLine.TenderInfo?.[0];
        if (tenderInfo && tenderInfo.Tender) {
          tenderType = tenderInfo.Tender[0].TenderCode?.[0] || tenderType;
        }
        
        const fuelLine = transLine.FuelLine?.[0];
        if (fuelLine) {
          const pumpNumber = fuelLine.FuelPositionID?.[0] || '';
          const quantity = parseFloat(fuelLine.SalesQuantity?.[0] || '0');
          const amount = parseFloat(fuelLine.SalesAmount?.[0] || '0');
          const description = fuelLine.Description?.[0] || 'Fuel';
          const unitPrice = parseFloat(fuelLine.ActualSalesPrice?.[0] || '0');

          if (lineStatus === 'cancel') {
            voidCount++;
            voidAmount += amount;
          } else {
            fuelVolume += quantity;
            fuelAmount += amount;
            totalAmount += amount;

            lineItems.push({
              posTransactionId: transactionId,
              itemType: 'fuel',
              upc: null,
              description,
              pumpNumber,
              quantity,
              amount,
            });

            if (pumpNumber) {
              if (dispenserMap.has(pumpNumber)) {
                const existing = dispenserMap.get(pumpNumber)!;
                existing.count++;
                existing.amount += amount;
                existing.volume += quantity;
              } else {
                dispenserMap.set(pumpNumber, {
                  pumpNumber,
                  count: 1,
                  amount,
                  volume: quantity,
                });
              }
            }

            const promotion = fuelLine.Promotion?.[0];
            if (promotion) {
              const promoId = promotion.PromotionID?.[0] || null;
              const promoAmount = parseFloat(promotion.PromotionAmount?.[0] || '0');
              loyalty.push({
                posTransactionId: transactionId,
                promotionId: promoId,
                promotionAmount: promoAmount,
              });
            }
          }
        }

        const merchLine = transLine.ItemLine?.[0];
        if (merchLine) {
          const itemCode = merchLine.ItemCode?.[0];
          const upc = itemCode?.POSCode?.[0] || null;
          const description = merchLine.Description?.[0] || null;
          const quantity = parseFloat(merchLine.SalesQuantity?.[0] || '0');
          const amount = parseFloat(merchLine.SalesAmount?.[0] || '0');

          if (lineStatus === 'cancel') {
            voidCount++;
            voidAmount += amount;
          } else {
            merchAmount += amount;
            totalAmount += amount;

            lineItems.push({
              posTransactionId: transactionId,
              itemType: 'merchandise',
              upc,
              description,
              pumpNumber: null,
              quantity,
              amount,
            });

            const promotion = merchLine.Promotion?.[0];
            if (promotion) {
              const promoId = promotion.PromotionID?.[0] || null;
              const promoAmount = parseFloat(promotion.PromotionAmount?.[0] || '0');
              loyalty.push({
                posTransactionId: transactionId,
                promotionId: promoId,
                promotionAmount: promoAmount,
              });
            }
          }
        }
      }

      if (transactionId && totalAmount > 0) {
        transactions.push({
          transactionId,
          transactionDateTime: eventDateTime,
          cashierId,
          fuelVolume,
          fuelAmount,
          merchAmount,
          totalAmount,
          tenderType,
        });
      }
    }

    const financialEvents = root.FinancialEvent || [];
    for (const finEvent of financialEvents) {
      const safeDropDetail = finEvent.FinancialEventDetail?.[0]?.SafeDropDetail?.[0];
      if (safeDropDetail) {
        const dropAmount = safeDropDetail.DropAmount?.[0] || '';
        const envelopeId = safeDropDetail.EnvelopeID?.[0] || '';
        if (dropAmount === '0' && envelopeId.toLowerCase().includes('cancel')) {
          noSaleCount++;
        }
      }
    }

    return {
      transactions,
      lineItems,
      loyalty,
      summary: {
        voidCount,
        voidAmount,
        noSaleCount,
      },
      dispensers: Array.from(dispenserMap.values()),
    };
  } catch (error) {
    console.log('Error parsing CPJR XML:', error);
    throw new Error(`Failed to parse CPJR XML: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
