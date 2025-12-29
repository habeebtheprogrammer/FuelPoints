export const generateAccountNumber = (): string => {
  const timestamp = Date.now().toString();
  const randomPart = Math.floor(Math.random() * 1000000).toString().padStart(6, '0');
  const accountNum = `${timestamp}${randomPart}`;
  return accountNum.slice(-10).padStart(10, '0');
};

export const generateLoyaltyId = (accountNumber: string): string => {
  return `99${accountNumber}`;
};
