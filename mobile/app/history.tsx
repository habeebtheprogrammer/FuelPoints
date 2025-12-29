import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  Modal,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, Spacing, FontSize, BorderRadius, Shadows } from '../constants/theme';
import { API_BASE_URL } from '../constants/api';

interface LineItem {
  upc: string;
  description: string;
  quantity: number;
  price: number;
  amount: number;
}

interface Transaction {
  id: number;
  transactionId: string;
  transactionDate: string;
  netAmount: number;
  subtotal: number;
  totalDiscount: number;
  promotionDiscount: number;
  pointsDiscount: number;
  pointsEarned: number;
  pointsRedeemed: number;
  pdiStoreNumber: string;
  promotionUsed: boolean;
  promotionNames: string | null;
  lineItems: LineItem[];
  itemCount: number;
}

export default function HistoryScreen() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedTx, setSelectedTx] = useState<Transaction | null>(null);

  useEffect(() => {
    loadTransactions();
  }, []);

  const loadTransactions = async () => {
    try {
      const stored = await AsyncStorage.getItem('customer');
      if (!stored) return;

      const customer = JSON.parse(stored);
      const response = await fetch(
        `${API_BASE_URL}/api/loyalty/customer/${customer.id}/transactions`
      );

      if (response.ok) {
        const data = await response.json();
        const txns = Array.isArray(data) ? data : (data.transactions || []);
        setTransactions(txns);
      } else {
        setTransactions([]);
      }
    } catch (err) {
      console.log('Transactions not available:', err);
      setTransactions([]);
    } finally {
      setLoading(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadTransactions();
    setRefreshing(false);
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return 'N/A';
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '';
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  };

  const formatCurrency = (amount: number | string | undefined) => {
    const num = typeof amount === 'string' ? parseFloat(amount) : (amount || 0);
    return `$${num.toFixed(2)}`;
  };

  const renderTransaction = ({ item }: { item: Transaction }) => (
    <TouchableOpacity 
      style={styles.transactionCard}
      onPress={() => setSelectedTx(item)}
      activeOpacity={0.7}
    >
      <View style={styles.transactionHeader}>
        <View>
          <Text style={styles.transactionDate}>{formatDate(item.transactionDate)}</Text>
          <Text style={styles.transactionTime}>{formatTime(item.transactionDate)}</Text>
        </View>
        <Text style={styles.transactionTotal}>
          {formatCurrency(item.netAmount)}
        </Text>
      </View>

      <View style={styles.transactionDetails}>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Store</Text>
          <Text style={styles.detailValue}>#{item.pdiStoreNumber || 'N/A'}</Text>
        </View>

        {(item.pointsEarned || 0) > 0 && (
          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Points Earned</Text>
            <Text style={[styles.detailValue, styles.pointsEarned]}>
              +{item.pointsEarned}
            </Text>
          </View>
        )}

        {(item.pointsRedeemed || 0) > 0 && (
          <View style={styles.detailRow}>
            <Text style={styles.detailLabel}>Points Redeemed</Text>
            <Text style={[styles.detailValue, styles.pointsRedeemed]}>
              -{item.pointsRedeemed}
            </Text>
          </View>
        )}
      </View>

      <View style={styles.viewReceiptRow}>
        <Text style={styles.viewReceiptText}>Tap to view receipt →</Text>
      </View>
    </TouchableOpacity>
  );

  const renderEmpty = () => (
    <View style={styles.emptyContainer}>
      <Text style={styles.emptyIcon}>🧾</Text>
      <Text style={styles.emptyTitle}>No transactions yet</Text>
      <Text style={styles.emptySubtitle}>
        Your purchase history will appear here
      </Text>
    </View>
  );

  const renderReceiptModal = () => (
    <Modal
      visible={selectedTx !== null}
      animationType="slide"
      transparent={true}
      onRequestClose={() => setSelectedTx(null)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Receipt Details</Text>
            <TouchableOpacity onPress={() => setSelectedTx(null)}>
              <Text style={styles.modalClose}>✕</Text>
            </TouchableOpacity>
          </View>
          
          {selectedTx && (
            <ScrollView style={styles.receiptScroll}>
              <View style={styles.receiptSection}>
                <Text style={styles.receiptStoreName}>Birdies Gas Station</Text>
                <Text style={styles.receiptStoreNumber}>Store #{selectedTx.pdiStoreNumber}</Text>
                <Text style={styles.receiptDate}>
                  {formatDate(selectedTx.transactionDate)} at {formatTime(selectedTx.transactionDate)}
                </Text>
                <Text style={styles.receiptTxId}>Transaction: {selectedTx.transactionId}</Text>
              </View>

              <View style={styles.receiptDivider} />

              {selectedTx.lineItems && selectedTx.lineItems.length > 0 && (
                <View style={styles.receiptSection}>
                  <Text style={styles.pointsSectionTitle}>Items Purchased</Text>
                  {selectedTx.lineItems.map((item, idx) => (
                    <View key={idx} style={styles.lineItemRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.lineItemDesc}>{item.description || 'Item'}</Text>
                        <Text style={styles.lineItemMeta}>
                          {item.quantity || 1} × {formatCurrency(item.price || item.amount)}
                        </Text>
                      </View>
                      <Text style={styles.lineItemPrice}>{formatCurrency(item.amount)}</Text>
                    </View>
                  ))}
                </View>
              )}

              <View style={styles.receiptDivider} />

              <View style={styles.receiptSection}>
                <View style={styles.receiptRow}>
                  <Text style={styles.receiptLabel}>Subtotal</Text>
                  <Text style={styles.receiptValue}>{formatCurrency(selectedTx.subtotal)}</Text>
                </View>
                
                {(selectedTx.promotionDiscount || 0) > 0 && (
                  <View style={styles.receiptRow}>
                    <Text style={styles.receiptLabel}>Promo Discount</Text>
                    <Text style={[styles.receiptValue, styles.discountText]}>
                      -{formatCurrency(selectedTx.promotionDiscount)}
                    </Text>
                  </View>
                )}

                {(selectedTx.pointsDiscount || 0) > 0 && (
                  <View style={styles.receiptRow}>
                    <Text style={styles.receiptLabel}>Points Discount</Text>
                    <Text style={[styles.receiptValue, styles.discountText]}>
                      -{formatCurrency(selectedTx.pointsDiscount)}
                    </Text>
                  </View>
                )}

                <View style={styles.receiptDivider} />

                <View style={styles.receiptRow}>
                  <Text style={styles.receiptTotalLabel}>Total</Text>
                  <Text style={styles.receiptTotalValue}>
                    {formatCurrency(selectedTx.netAmount)}
                  </Text>
                </View>
              </View>

              <View style={styles.receiptDivider} />

              <View style={styles.receiptSection}>
                <Text style={styles.pointsSectionTitle}>Loyalty Points</Text>
                
                <View style={styles.receiptRow}>
                  <Text style={styles.receiptLabel}>Points Earned</Text>
                  <Text style={[styles.receiptValue, styles.pointsEarned]}>
                    +{selectedTx.pointsEarned || 0}
                  </Text>
                </View>

                {(selectedTx.pointsRedeemed || 0) > 0 && (
                  <View style={styles.receiptRow}>
                    <Text style={styles.receiptLabel}>Points Redeemed</Text>
                    <Text style={[styles.receiptValue, styles.pointsRedeemed]}>
                      -{selectedTx.pointsRedeemed}
                    </Text>
                  </View>
                )}
              </View>

              {selectedTx.promotionUsed && selectedTx.promotionNames && (
                <>
                  <View style={styles.receiptDivider} />
                  <View style={styles.receiptSection}>
                    <Text style={styles.pointsSectionTitle}>Promotions Applied</Text>
                    <Text style={styles.promotionText}>{selectedTx.promotionNames}</Text>
                  </View>
                </>
              )}

              <View style={styles.receiptFooter}>
                <Text style={styles.thankYouText}>Thank you for shopping with us!</Text>
              </View>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Transaction History</Text>
        <View style={styles.placeholder} />
      </View>

      {loading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      ) : (
        <FlatList
          data={transactions}
          keyExtractor={(item) => item.id.toString()}
          renderItem={renderTransaction}
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={renderEmpty}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={Colors.primary}
            />
          }
          showsVerticalScrollIndicator={false}
        />
      )}

      {renderReceiptModal()}
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    padding: Spacing.lg,
    paddingBottom: Spacing.xxl,
  },
  transactionCard: {
    backgroundColor: Colors.surface,
    borderRadius: BorderRadius.lg,
    padding: Spacing.lg,
    marginBottom: Spacing.md,
    ...Shadows.sm,
  },
  transactionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: Spacing.md,
    paddingBottom: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  transactionDate: {
    fontSize: FontSize.md,
    fontWeight: '600',
    color: Colors.text,
  },
  transactionTime: {
    fontSize: FontSize.sm,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  transactionTotal: {
    fontSize: FontSize.xl,
    fontWeight: '700',
    color: Colors.text,
  },
  transactionDetails: {
    gap: Spacing.sm,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  detailLabel: {
    fontSize: FontSize.sm,
    color: Colors.textSecondary,
  },
  detailValue: {
    fontSize: FontSize.sm,
    fontWeight: '600',
    color: Colors.text,
  },
  pointsEarned: {
    color: Colors.success,
  },
  pointsRedeemed: {
    color: Colors.error,
  },
  viewReceiptRow: {
    marginTop: Spacing.md,
    paddingTop: Spacing.sm,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    alignItems: 'center',
  },
  viewReceiptText: {
    fontSize: FontSize.sm,
    color: Colors.primary,
    fontWeight: '500',
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: Spacing.xxl * 2,
  },
  emptyIcon: {
    fontSize: 64,
    marginBottom: Spacing.lg,
  },
  emptyTitle: {
    fontSize: FontSize.xl,
    fontWeight: '700',
    color: Colors.text,
    marginBottom: Spacing.sm,
  },
  emptySubtitle: {
    fontSize: FontSize.md,
    color: Colors.textSecondary,
    textAlign: 'center',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: Colors.surface,
    borderTopLeftRadius: BorderRadius.xl,
    borderTopRightRadius: BorderRadius.xl,
    maxHeight: '80%',
    ...Shadows.lg,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  modalTitle: {
    fontSize: FontSize.lg,
    fontWeight: '700',
    color: Colors.text,
  },
  modalClose: {
    fontSize: FontSize.xl,
    color: Colors.textSecondary,
    padding: Spacing.sm,
  },
  receiptScroll: {
    padding: Spacing.lg,
  },
  receiptSection: {
    paddingVertical: Spacing.md,
  },
  receiptStoreName: {
    fontSize: FontSize.lg,
    fontWeight: '700',
    color: Colors.text,
    textAlign: 'center',
  },
  receiptStoreNumber: {
    fontSize: FontSize.md,
    color: Colors.textSecondary,
    textAlign: 'center',
    marginTop: Spacing.xs,
  },
  receiptDate: {
    fontSize: FontSize.sm,
    color: Colors.textSecondary,
    textAlign: 'center',
    marginTop: Spacing.xs,
  },
  receiptTxId: {
    fontSize: FontSize.xs,
    color: Colors.textSecondary,
    textAlign: 'center',
    marginTop: Spacing.xs,
  },
  receiptDivider: {
    height: 1,
    backgroundColor: Colors.border,
    marginVertical: Spacing.sm,
  },
  receiptRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: Spacing.xs,
  },
  receiptLabel: {
    fontSize: FontSize.md,
    color: Colors.textSecondary,
  },
  receiptValue: {
    fontSize: FontSize.md,
    fontWeight: '500',
    color: Colors.text,
  },
  receiptTotalLabel: {
    fontSize: FontSize.lg,
    fontWeight: '700',
    color: Colors.text,
  },
  receiptTotalValue: {
    fontSize: FontSize.xl,
    fontWeight: '700',
    color: Colors.text,
  },
  discountText: {
    color: Colors.success,
  },
  pointsSectionTitle: {
    fontSize: FontSize.md,
    fontWeight: '600',
    color: Colors.text,
    marginBottom: Spacing.sm,
  },
  promotionText: {
    fontSize: FontSize.sm,
    color: Colors.primary,
    fontStyle: 'italic',
  },
  lineItemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingVertical: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  lineItemDesc: {
    fontSize: FontSize.sm,
    color: Colors.text,
    fontWeight: '500',
  },
  lineItemMeta: {
    fontSize: FontSize.xs,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  lineItemPrice: {
    fontSize: FontSize.sm,
    fontWeight: '600',
    color: Colors.text,
  },
  receiptFooter: {
    paddingVertical: Spacing.xl,
    alignItems: 'center',
  },
  thankYouText: {
    fontSize: FontSize.sm,
    color: Colors.textSecondary,
    fontStyle: 'italic',
  },
});
