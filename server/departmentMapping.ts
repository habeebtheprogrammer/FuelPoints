// Department mapping for Gilbarco Passport POS categories
// Maps Product Category codes to Department codes and names

export interface DepartmentMapping {
  categoryCode: string;
  categoryName: string;
  departmentCode: string;
  departmentName: string;
}

export const DEPARTMENT_MAP: Record<string, DepartmentMapping> = {
  '2': { categoryCode: '2', categoryName: '02 Cigarettes', departmentCode: '101', departmentName: '101 Cigarettes' },
  '3': { categoryCode: '3', categoryName: '03 Other Tobacco', departmentCode: '102', departmentName: '102 Other Tobacco' },
  '4': { categoryCode: '4', categoryName: '04 Beer', departmentCode: '103', departmentName: '103 Alcoholic Beverages' },
  '5': { categoryCode: '5', categoryName: '05 Wine', departmentCode: '103', departmentName: '103 Alcoholic Beverages' },
  '6': { categoryCode: '6', categoryName: '06 Liquor', departmentCode: '103', departmentName: '103 Alcoholic Beverages' },
  '7': { categoryCode: '7', categoryName: '07 Package Bev (non Alch)', departmentCode: '104', departmentName: '104 Packaged Beverages' },
  '8': { categoryCode: '8', categoryName: '08 Candy', departmentCode: '105', departmentName: '105 Candy' },
  '9': { categoryCode: '9', categoryName: '09 Fluid Milk Products', departmentCode: '106', departmentName: '106 Dairy' },
  '10': { categoryCode: '10', categoryName: '10 Other Dairy And Deli', departmentCode: '106', departmentName: '106 Dairy' },
  '11': { categoryCode: '11', categoryName: '11 Commissary & Oth Pkg Prods', departmentCode: '107', departmentName: '107 Packaged Commissary' },
  '12': { categoryCode: '12', categoryName: '12 Pkg Ice Cream/novelities', departmentCode: '108', departmentName: '108 Ice Cream' },
  '13': { categoryCode: '13', categoryName: '13 Frozen Foods', departmentCode: '110', departmentName: '110 Grocery' },
  '14': { categoryCode: '14', categoryName: '14 Packaged Bread', departmentCode: '110', departmentName: '110 Grocery' },
  '15': { categoryCode: '15', categoryName: '15 Salty Snacks', departmentCode: '109', departmentName: '109 Snacks' },
  '16': { categoryCode: '16', categoryName: '16 Packaged Sweet Snacks', departmentCode: '109', departmentName: '109 Snacks' },
  '17': { categoryCode: '17', categoryName: '17 Alternative Snacks', departmentCode: '109', departmentName: '109 Snacks' },
  '18': { categoryCode: '18', categoryName: '18 Perishable Grocery', departmentCode: '107', departmentName: '107 Packaged Commissary' },
  '19': { categoryCode: '19', categoryName: '19 Edible Grocery', departmentCode: '110', departmentName: '110 Grocery' },
  '20': { categoryCode: '20', categoryName: '20 Non Edible Grocery', departmentCode: '110', departmentName: '110 Grocery' },
  '21': { categoryCode: '21', categoryName: '21 Health & Beauty Care', departmentCode: '112', departmentName: '112 General Merchandise' },
  '22': { categoryCode: '22', categoryName: '22 General Merchandise', departmentCode: '112', departmentName: '112 General Merchandise' },
  '23': { categoryCode: '23', categoryName: '23 Publications', departmentCode: '112', departmentName: '112 General Merchandise' },
  '24': { categoryCode: '24', categoryName: '24 Automotive Products', departmentCode: '112', departmentName: '112 General Merchandise' },
  '25': { categoryCode: '25', categoryName: '25 Automotive Services', departmentCode: '900', departmentName: '900 Expense' },
  '26': { categoryCode: '26', categoryName: '26 Store Services (fee-based)', departmentCode: '900', departmentName: '900 Expense' },
  '27': { categoryCode: '27', categoryName: '27 Scratch Lottery', departmentCode: '114', departmentName: '114  Scratch Lottery' },
  '28': { categoryCode: '28', categoryName: '28 Ice', departmentCode: '110', departmentName: '110 Grocery' },
  '29': { categoryCode: '29', categoryName: '29 Foodservice Prep On-site', departmentCode: '201', departmentName: '201 Foodservice' },
  '30': { categoryCode: '30', categoryName: '30 Hot Dispensed Beverages', departmentCode: '202', departmentName: '202 Hot Dispensed Beverages' },
  '31': { categoryCode: '31', categoryName: '31 Cold Dispensed Beverages', departmentCode: '203', departmentName: '203 Cold Dispensed Beverages' },
  '32': { categoryCode: '32', categoryName: '32 Frozen Dispensed Beverages', departmentCode: '203', departmentName: '203 Cold Dispensed Beverages' },
  '33': { categoryCode: '33', categoryName: '33 Pre-paid Cards', departmentCode: '112', departmentName: '112 General Merchandise' },
  '60': { categoryCode: '60', categoryName: '60 JUUL Devices', departmentCode: '102', departmentName: '102 Other Tobacco' },
  '61': { categoryCode: '61', categoryName: '61 JUUL Pods', departmentCode: '102', departmentName: '102 Other Tobacco' },
  '90': { categoryCode: '90', categoryName: '90 Online Lotto', departmentCode: '900', departmentName: '900 Expense' },
  '91': { categoryCode: '91', categoryName: '91 Lottery Vending', departmentCode: '900', departmentName: '900 Expense' },
  '92': { categoryCode: '92', categoryName: '92 Lotto Payouts', departmentCode: '900', departmentName: '900 Expense' },
  '93': { categoryCode: '93', categoryName: '93 Scratch Payout', departmentCode: '900', departmentName: '900 Expense' },
  '94': { categoryCode: '94', categoryName: '94 Mobile Coupons', departmentCode: '900', departmentName: '900 Expense' },
  '97': { categoryCode: '97', categoryName: '97 Tax Charges', departmentCode: '900', departmentName: '900 Expense' },
  '98': { categoryCode: '98', categoryName: '98 Invoice Fees', departmentCode: '900', departmentName: '900 Expense' },
  '99': { categoryCode: '99', categoryName: '99 Expense', departmentCode: '900', departmentName: '900 Expense' },
  '501': { categoryCode: '501', categoryName: '501 General Merch SBT', departmentCode: '500', departmentName: '500 Scan Based Trading' },
};

export function getDepartmentForCategory(categoryCode: string): DepartmentMapping | null {
  return DEPARTMENT_MAP[categoryCode] || null;
}

export function getAllDepartments(): DepartmentMapping[] {
  return Object.values(DEPARTMENT_MAP);
}

export function groupByDepartment<T extends { category?: string | null }>(
  items: T[]
): Record<string, { department: DepartmentMapping; items: T[] }> {
  const grouped: Record<string, { department: DepartmentMapping; items: T[] }> = {};
  
  for (const item of items) {
    const categoryCode = item.category?.toString() || '99'; // Default to Expense
    const dept = getDepartmentForCategory(categoryCode);
    
    if (dept) {
      const key = dept.departmentCode;
      if (!grouped[key]) {
        grouped[key] = { department: dept, items: [] };
      }
      grouped[key].items.push(item);
    }
  }
  
  return grouped;
}
