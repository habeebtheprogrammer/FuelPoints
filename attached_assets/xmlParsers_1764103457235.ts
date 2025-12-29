import { detectPOSFormat } from './parserRegistry';
import {
  parseFGM as parsePassportFGM,
  parseISM as parsePassportISM,
  parseMCM as parsePassportMCM,
  parseCPJR as parsePassportCPJR,
  type FuelGradeData,
  type ItemSalesData,
  type DepartmentData,
  type CPJRData,
} from './passportParsers';
import {
  parseVerifoneFGM,
  parseVerifoneISM,
  parseVerifoneMCM,
  parseVerifoneCPJR,
} from './verifoneParsers';

export type { FuelGradeData, ItemSalesData, DepartmentData, CPJRData };

export async function parseFGM(xmlContent: string, businessDate: string): Promise<FuelGradeData[]> {
  const format = await detectPOSFormat(xmlContent);
  
  if (format === 'verifone') {
    return parseVerifoneFGM(xmlContent, businessDate);
  } else {
    return parsePassportFGM(xmlContent, businessDate);
  }
}

export async function parseISM(xmlContent: string, businessDate: string): Promise<{ items: ItemSalesData[], departments: DepartmentData[] }> {
  const format = await detectPOSFormat(xmlContent);
  
  if (format === 'verifone') {
    return parseVerifoneISM(xmlContent, businessDate);
  } else {
    return parsePassportISM(xmlContent, businessDate);
  }
}

export async function parseMCM(xmlContent: string, businessDate: string): Promise<DepartmentData[]> {
  const format = await detectPOSFormat(xmlContent);
  
  if (format === 'verifone') {
    return parseVerifoneMCM(xmlContent, businessDate);
  } else {
    return parsePassportMCM(xmlContent, businessDate);
  }
}

export async function parseCPJR(xmlContent: string, businessDate: string): Promise<CPJRData> {
  const format = await detectPOSFormat(xmlContent);
  
  if (format === 'verifone') {
    return parseVerifoneCPJR(xmlContent, businessDate);
  } else {
    return parsePassportCPJR(xmlContent, businessDate);
  }
}
