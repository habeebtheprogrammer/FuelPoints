export const generateAccountNumber = (): string => {
  const timestamp = Date.now().toString();
  const randomPart = Math.floor(Math.random() * 1000000).toString().padStart(6, '0');
  const accountNum = `${timestamp}${randomPart}`;
  return accountNum.slice(-10).padStart(10, '0');
};

export const generateLoyaltyId = (accountNumber: string): string => {
  return `99${accountNumber}`;
};

export const normalizeUpcVariants = (rawUpc: string): string[] => {
  const clean = (rawUpc || '').trim();
  if (!clean) return [];
  
  const variants = new Set<string>();
  
  variants.add(clean);
  
  const stripped = clean.replace(/^0+/, '');
  if (stripped) variants.add(stripped);
  
  variants.add(stripped.padStart(12, '0'));
  variants.add(stripped.padStart(13, '0'));
  variants.add(stripped.padStart(14, '0'));
  
  if (clean.length <= 12) {
    variants.add(clean.padStart(12, '0'));
  }
  
  return Array.from(variants);
};

export const upcMatchesAny = (posUpc: string, storedUpcs: string[]): boolean => {
  const posVariants = normalizeUpcVariants(posUpc);
  for (const storedUpc of storedUpcs) {
    const storedVariants = normalizeUpcVariants(storedUpc);
    for (const pv of posVariants) {
      if (storedVariants.includes(pv)) {
        return true;
      }
    }
  }
  return false;
};
