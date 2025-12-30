import { parseStringPromise } from 'xml2js';

export type POSFormat = 'passport' | 'verifone';
export type ReportType = 'FGM' | 'ISM' | 'MCM' | 'CPJR' | 'MISC';

export async function detectPOSFormat(xmlContent: string): Promise<POSFormat> {
  try {
    const firstLine = xmlContent.split('\n').slice(0, 5).join('\n');
    
    if (firstLine.includes('NAXML-')) {
      return 'passport';
    }
    
    if (firstLine.includes('fuel:fuelTotals') || 
        firstLine.includes('vs:journal') ||
        firstLine.includes('merch:') ||
        firstLine.includes('urn:vfi-sapphire') ||
        firstLine.toLowerCase().includes('<transset')) {
      return 'verifone';
    }
    
    const result = await parseStringPromise(xmlContent);
    const rootKeys = Object.keys(result);
    
    if (rootKeys.some(key => key.startsWith('NAXML-'))) {
      return 'passport';
    }
    
    if (rootKeys.some(key => key === 'transSet') ||
        rootKeys.some(key => key.includes(':') || 
        rootKeys.some(key => result[key]?.[0]?.$ && 
          JSON.stringify(result[key][0].$).includes('vfi-sapphire')))) {
      return 'verifone';
    }
    
    console.warn('Unknown POS format, defaulting to passport');
    return 'passport';
  } catch (error) {
    console.log('Error detecting POS format:', error);
    return 'passport';
  }
}

export interface ParserResult {
  success: boolean;
  data?: any;
  error?: string;
}

export interface Parser {
  parseFGM(xmlContent: string, businessDate: string): Promise<any[]>;
  parseISM(xmlContent: string, businessDate: string): Promise<any>;
  parseMCM(xmlContent: string, businessDate: string): Promise<any[]>;
  parseCPJR(xmlContent: string, businessDate: string): Promise<any[]>;
}
