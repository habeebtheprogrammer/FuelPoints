import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Dimensions,
  Image,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, Spacing, FontSize, BorderRadius, Shadows } from '../constants/theme';

const { width } = Dimensions.get('window');

interface Customer {
  id: number;
  firstName: string;
  lastName: string;
  phone: string;
  loyaltyId: string;
  pointsBalance: number;
}

const CODE128_PATTERNS: string[] = [
  '11011001100', '11001101100', '11001100110', '10010011000', '10010001100',
  '10001001100', '10011001000', '10011000100', '10001100100', '11001001000',
  '11001000100', '11000101000', '10110011100', '10011011100', '10011001110',
  '10111001100', '10011101100', '10011100110', '11001110010', '11001011100',
  '11001001110', '11011100100', '11001110100', '11101101110', '11101001100',
  '11100101100', '11100100110', '11101100100', '11100110100', '11100110010',
  '11011011000', '11011000110', '11000110110', '10100011000', '10001011000',
  '10001000110', '10110001000', '10001101000', '10001100010', '11010001000',
  '11000101000', '11000100010', '10110111000', '10110001110', '10001101110',
  '10111011000', '10111000110', '10001110110', '11101110110', '11010001110',
  '11000101110', '11011101000', '11011100010', '11011101110', '11101011000',
  '11101000110', '11100010110', '11101101000', '11101100010', '11100011010',
  '11101111010', '11001000010', '11110001010', '10100110000', '10100001100',
  '10010110000', '10010000110', '10000101100', '10000100110', '10110010000',
  '10110000100', '10011010000', '10011000010', '10000110100', '10000110010',
  '11000010010', '11001010000', '11110111010', '11000010100', '10001111010',
  '10100111100', '10010111100', '10010011110', '10111100100', '10011110100',
  '10011110010', '11110100100', '11110010100', '11110010010', '11011011110',
  '11011110110', '11110110110', '10101111000', '10100011110', '10001011110',
  '10111101000', '10111100010', '11110101000', '11110100010', '10111011110',
  '10111101110', '11101011110', '11110101110', '11010000100', '11010010000',
  '11010011100', '1100011101011',
];

const START_B = 104;
const STOP_INDEX = 106;

function getCode128Value(char: string): number {
  const code = char.charCodeAt(0);
  if (code >= 32 && code <= 126) {
    return code - 32;
  }
  return 0;
}

function generateCode128Bars(data: string): boolean[] {
  const bars: boolean[] = [];
  
  const startPattern = CODE128_PATTERNS[START_B];
  for (const bit of startPattern) {
    bars.push(bit === '1');
  }
  
  let checksum = START_B;
  
  for (let i = 0; i < data.length; i++) {
    const charValue = getCode128Value(data[i]);
    checksum += charValue * (i + 1);
    
    const pattern = CODE128_PATTERNS[charValue];
    if (pattern) {
      for (const bit of pattern) {
        bars.push(bit === '1');
      }
    }
  }
  
  const checksumValue = checksum % 103;
  const checksumPattern = CODE128_PATTERNS[checksumValue];
  for (const bit of checksumPattern) {
    bars.push(bit === '1');
  }
  
  const stopPattern = CODE128_PATTERNS[STOP_INDEX];
  for (const bit of stopPattern) {
    bars.push(bit === '1');
  }
  
  return bars;
}

function SimpleBarcode({ value }: { value: string }) {
  if (!value) {
    return (
      <View style={barcodeStyles.placeholder}>
        <Text style={barcodeStyles.placeholderText}>Loading...</Text>
      </View>
    );
  }

  const bars = generateCode128Bars(value);
  const barWidth = Math.max(1.5, (width - 120) / bars.length);

  return (
    <View style={barcodeStyles.container}>
      <View style={barcodeStyles.barsContainer}>
        {bars.map((isBlack, index) => (
          <View
            key={index}
            style={[
              barcodeStyles.bar,
              {
                width: barWidth,
                backgroundColor: isBlack ? Colors.text : Colors.surface,
              },
            ]}
          />
        ))}
      </View>
    </View>
  );
}

const barcodeStyles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.md,
  },
  barsContainer: {
    flexDirection: 'row',
    height: 80,
    backgroundColor: Colors.surface,
    borderRadius: BorderRadius.sm,
    overflow: 'hidden',
  },
  bar: {
    height: '100%',
  },
  placeholder: {
    height: 80,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: Colors.surfaceAlt,
    borderRadius: BorderRadius.sm,
    width: '100%',
  },
  placeholderText: {
    color: Colors.textSecondary,
  },
});

export default function BarcodeScreen() {
  const [customer, setCustomer] = useState<Customer | null>(null);

  useEffect(() => {
    loadCustomer();
  }, []);

  const loadCustomer = async () => {
    try {
      const stored = await AsyncStorage.getItem('customer');
      if (stored) {
        setCustomer(JSON.parse(stored));
      }
    } catch (err) {
      console.log('Error loading customer:', err);
    }
  };

  const getLoyaltyNumber = () => {
    if (!customer?.loyaltyId) return '';
    const digits = customer.loyaltyId.replace(/\D/g, '');
    return digits;
  };

  const formatLoyaltyId = (id: string) => {
    if (!id) return 'Loading...';
    return id.replace(/(\d{4})/g, '$1 ').trim();
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>My Loyalty Card</Text>
        <View style={styles.placeholder} />
      </View>

      <View style={styles.content}>
        <LinearGradient colors={Colors.gradient.primary} style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.logoContainer}>
              <Image
                source={require('../assets/birdies-logo.jpg')}
                style={styles.cardLogo}
                resizeMode="contain"
              />
            </View>
          </View>

          <View style={styles.memberInfo}>
            <Text style={styles.memberLabel}>Member</Text>
            <Text style={styles.memberName}>
              {customer?.firstName} {customer?.lastName}
            </Text>
          </View>

          <View style={styles.barcodeContainer}>
            <View style={styles.barcodeWrapper}>
              <SimpleBarcode value={getLoyaltyNumber()} />
            </View>
            <Text style={styles.barcodeNumber}>
              {formatLoyaltyId(getLoyaltyNumber())}
            </Text>
          </View>

          <View style={styles.cardFooter}>
            <View style={styles.pointsInfo}>
              <Text style={styles.pointsLabel}>Points Balance</Text>
              <Text style={styles.pointsValue}>
                {customer?.pointsBalance?.toLocaleString() || 0}
              </Text>
            </View>
          </View>
        </LinearGradient>

        <View style={styles.instructions}>
          <Text style={styles.instructionsTitle}>How to use</Text>
          <View style={styles.instructionItem}>
            <Text style={styles.instructionNumber}>1</Text>
            <Text style={styles.instructionText}>
              Show this barcode at checkout
            </Text>
          </View>
          <View style={styles.instructionItem}>
            <Text style={styles.instructionNumber}>2</Text>
            <Text style={styles.instructionText}>
              Cashier will scan to apply your rewards
            </Text>
          </View>
          <View style={styles.instructionItem}>
            <Text style={styles.instructionNumber}>3</Text>
            <Text style={styles.instructionText}>
              Earn 5 points for every $1 spent
            </Text>
          </View>
        </View>

        <View style={styles.tipCard}>
          <Text style={styles.tipIcon}>💡</Text>
          <View style={styles.tipContent}>
            <Text style={styles.tipTitle}>Pro Tip</Text>
            <Text style={styles.tipText}>
              Increase your screen brightness for easier scanning!
            </Text>
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
  },
  backButton: {
    padding: Spacing.sm,
  },
  backText: {
    fontSize: FontSize.md,
    color: Colors.primary,
    fontWeight: '600',
  },
  headerTitle: {
    fontSize: FontSize.lg,
    fontWeight: '700',
    color: Colors.text,
  },
  placeholder: {
    width: 60,
  },
  content: {
    flex: 1,
    padding: Spacing.lg,
  },
  card: {
    borderRadius: BorderRadius.xl,
    padding: Spacing.xl,
    marginBottom: Spacing.xl,
    ...Shadows.lg,
  },
  cardHeader: {
    alignItems: 'center',
    marginBottom: Spacing.lg,
  },
  logoContainer: {
    backgroundColor: 'rgba(255,255,255,0.95)',
    borderRadius: BorderRadius.lg,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
  },
  cardLogo: {
    width: 180,
    height: 55,
  },
  memberInfo: {
    marginBottom: Spacing.lg,
  },
  memberLabel: {
    fontSize: FontSize.sm,
    color: 'rgba(255, 255, 255, 0.7)',
    marginBottom: 4,
  },
  memberName: {
    fontSize: FontSize.xl,
    fontWeight: '600',
    color: Colors.surface,
  },
  barcodeContainer: {
    backgroundColor: Colors.surface,
    borderRadius: BorderRadius.lg,
    padding: Spacing.md,
    marginBottom: Spacing.lg,
  },
  barcodeWrapper: {
    alignItems: 'center',
    marginBottom: Spacing.sm,
  },
  barcodeNumber: {
    textAlign: 'center',
    fontSize: FontSize.lg,
    fontWeight: '600',
    color: Colors.text,
    letterSpacing: 2,
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'center',
  },
  pointsInfo: {
    alignItems: 'center',
  },
  pointsLabel: {
    fontSize: FontSize.sm,
    color: 'rgba(255, 255, 255, 0.7)',
    marginBottom: 4,
  },
  pointsValue: {
    fontSize: FontSize.xxl,
    fontWeight: '700',
    color: Colors.surface,
  },
  instructions: {
    backgroundColor: Colors.surface,
    borderRadius: BorderRadius.lg,
    padding: Spacing.lg,
    marginBottom: Spacing.lg,
    ...Shadows.sm,
  },
  instructionsTitle: {
    fontSize: FontSize.lg,
    fontWeight: '700',
    color: Colors.text,
    marginBottom: Spacing.md,
  },
  instructionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.md,
  },
  instructionNumber: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: Colors.primary,
    color: Colors.surface,
    fontSize: FontSize.md,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 28,
    marginRight: Spacing.md,
    overflow: 'hidden',
  },
  instructionText: {
    flex: 1,
    fontSize: FontSize.md,
    color: Colors.text,
  },
  tipCard: {
    flexDirection: 'row',
    backgroundColor: Colors.accent + '20',
    borderRadius: BorderRadius.lg,
    padding: Spacing.lg,
    ...Shadows.sm,
  },
  tipIcon: {
    fontSize: 24,
    marginRight: Spacing.md,
  },
  tipContent: {
    flex: 1,
  },
  tipTitle: {
    fontSize: FontSize.md,
    fontWeight: '600',
    color: Colors.text,
    marginBottom: 4,
  },
  tipText: {
    fontSize: FontSize.sm,
    color: Colors.textSecondary,
  },
});
