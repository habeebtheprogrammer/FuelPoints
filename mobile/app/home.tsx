import { useEffect, useState, useCallback } from 'react';
import { router, useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
  Dimensions,
  Image,
  Modal,
  Animated,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors } from '../constants/theme';
import { API_BASE_URL } from '../constants/api';

const { width } = Dimensions.get('window');

interface Customer {
  id: number;
  firstName: string;
  lastName: string;
  phone: string;
  loyaltyId: string;
  pointsBalance: number;
}

interface PunchCard {
  punchCardId: number;
  punchCardName: string;
  itemGroupName: string | null;
  currentPunches: number;
  punchesRequired: number;
  rewardType: string;
  rewardValue: string;
  rewardReady: boolean;
  totalPunchesEarned: number;
  totalRewardsRedeemed: number;
  lastPunchDate: string | null;
  lastRewardDate: string | null;
  punchesRemaining: number;
}

interface Promotion {
  id: number;
  title: string;
  subtitle: string;
  image: string;
  color: string;
}

const FEATURED_PROMOTIONS: Promotion[] = [
  {
    id: 1,
    title: '2 for $6',
    subtitle: 'King Size Candy Bars',
    image: 'https://images.unsplash.com/photo-1621939514649-280e2ee25f60?w=400',
    color: '#8B4513',
  },
  {
    id: 2,
    title: '2 for $5',
    subtitle: '20oz Pepsi Products',
    image: 'https://images.unsplash.com/photo-1629203851122-3726ecdf080e?w=400',
    color: '#004B93',
  },
  {
    id: 3,
    title: '$1.99',
    subtitle: 'Any Size Coffee',
    image: 'https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=400',
    color: '#6F4E37',
  },
  {
    id: 4,
    title: '2 for $4',
    subtitle: 'Bottled Water 1L',
    image: 'https://images.unsplash.com/photo-1548839140-29a749e1cf4d?w=400',
    color: '#00A4E4',
  },
];

export default function HomeScreen() {
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [punchCards, setPunchCards] = useState<PunchCard[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [menuVisible, setMenuVisible] = useState(false);

  useFocusEffect(
    useCallback(() => {
      loadData();
    }, [])
  );

  const loadData = async () => {
    try {
      const stored = await AsyncStorage.getItem('customer');
      if (!stored) {
        router.replace('/');
        return;
      }

      const cust = JSON.parse(stored);
      setCustomer(cust);

      const [customerResponse, punchResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/pos/customer-lookup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phone: cust.phone }),
        }),
        fetch(`${API_BASE_URL}/api/punch-cards/customer/${cust.id}`).catch(() => null),
      ]);

      if (customerResponse.ok) {
        const data = await customerResponse.json();
        const updatedCustomer = {
          ...cust,
          pointsBalance: data.pointsBalance || 0,
        };
        setCustomer(updatedCustomer);
        await AsyncStorage.setItem('customer', JSON.stringify(updatedCustomer));
      }

      if (punchResponse && punchResponse.ok) {
        const data = await punchResponse.json();
        const cards = Array.isArray(data) ? data : (data.punchCards || []);
        setPunchCards(cards);
      }
    } catch (err) {
      console.log('Error loading data:', err);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  const handleLogout = async () => {
    await AsyncStorage.removeItem('customer');
    router.replace('/');
  };

  const getRewardText = (card: PunchCard) => {
    switch (card.rewardType) {
      case 'free_item':
        return 'FREE ITEM';
      case 'percent_off':
        return `${card.rewardValue}% OFF`;
      case 'dollar_off':
        return `$${card.rewardValue} OFF`;
      default:
        return 'REWARD';
    }
  };

  const totalPoints = customer?.pointsBalance || 0;
  const cashValue = (totalPoints / 10000).toFixed(2);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.primary} />
        }
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.headerBanner}>
          <TouchableOpacity style={styles.menuBtn} onPress={() => setMenuVisible(true)}>
            <Text style={styles.menuIcon}>☰</Text>
          </TouchableOpacity>
          <Image
            source={require('../assets/birdies-logo.jpg')}
            style={styles.headerLogo}
            resizeMode="contain"
          />
          <TouchableOpacity style={styles.locationBtn} onPress={() => router.push('/locations')}>
            <Text style={styles.locationIcon}>📍</Text>
          </TouchableOpacity>
        </View>

        <Modal
          visible={menuVisible}
          animationType="none"
          transparent={true}
          onRequestClose={() => setMenuVisible(false)}
        >
          <View style={styles.drawerContainer}>
            <TouchableOpacity 
              style={styles.drawerOverlay} 
              activeOpacity={1} 
              onPress={() => setMenuVisible(false)}
            />
            <View style={styles.drawerContent}>
              <SafeAreaView style={styles.drawerSafe} edges={['top']}>
                <View style={styles.drawerHeader}>
                  <TouchableOpacity style={styles.drawerClose} onPress={() => setMenuVisible(false)}>
                    <Text style={styles.drawerCloseIcon}>✕</Text>
                  </TouchableOpacity>
                </View>

                <View style={styles.drawerAccount}>
                  <View style={styles.accountIcon}>
                    <Text style={styles.accountEmoji}>👤</Text>
                  </View>
                  <View style={styles.accountInfo}>
                    <Text style={styles.accountTitle}>MY ACCOUNT</Text>
                    <Text style={styles.accountId}>Loyalty ID:</Text>
                    <Text style={styles.accountIdValue}>{customer?.loyaltyId || 'N/A'}</Text>
                  </View>
                  <TouchableOpacity style={styles.logoutBtnDrawer} onPress={() => { setMenuVisible(false); handleLogout(); }}>
                    <Text style={styles.logoutTextDrawer}>LOG OUT</Text>
                  </TouchableOpacity>
                </View>

                <ScrollView style={styles.drawerScroll} showsVerticalScrollIndicator={false}>
                  <TouchableOpacity 
                    style={styles.drawerItem} 
                    onPress={() => { setMenuVisible(false); router.push('/home'); }}
                  >
                    <Text style={styles.drawerItemIcon}>🏠</Text>
                    <Text style={styles.drawerItemText}>HOME</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    style={styles.drawerItem} 
                    onPress={() => { setMenuVisible(false); router.push('/barcode'); }}
                  >
                    <Text style={styles.drawerItemIcon}>📊</Text>
                    <Text style={styles.drawerItemText}>SCAN / PAY</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    style={styles.drawerItem} 
                    onPress={() => { setMenuVisible(false); router.push('/history'); }}
                  >
                    <Text style={styles.drawerItemIcon}>🕐</Text>
                    <Text style={styles.drawerItemText}>TRANSACTION HISTORY</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    style={styles.drawerItem} 
                    onPress={() => { setMenuVisible(false); router.push('/profile'); }}
                  >
                    <Text style={styles.drawerItemIcon}>⭐</Text>
                    <Text style={styles.drawerItemText}>MY PROFILE</Text>
                  </TouchableOpacity>

                  <View style={styles.drawerDivider} />

                  <TouchableOpacity 
                    style={styles.drawerItemSecondary} 
                    onPress={() => { setMenuVisible(false); router.push('/locations'); }}
                  >
                    <Text style={styles.drawerItemTextSecondary}>Locations</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={styles.drawerItemSecondary}>
                    <Text style={styles.drawerItemTextSecondary}>Get Help</Text>
                  </TouchableOpacity>
                </ScrollView>
              </SafeAreaView>
            </View>
          </View>
        </Modal>

        <Text style={styles.greeting}>Good {getGreeting()}, {customer?.firstName || 'Guest'}!</Text>
        <Text style={styles.tagline}>Keep collecting punches for FREE rewards!</Text>

        <TouchableOpacity style={styles.pointsSection} onPress={() => router.push('/barcode')}>
          <View style={styles.pointsHeader}>
            <Text style={styles.pointsLabel}>MY LOYALTY CARD</Text>
          </View>
          <View style={styles.pointsBalanceRow}>
            <Text style={styles.pointsValue}>{totalPoints.toLocaleString()}</Text>
            <Text style={styles.pointsUnit}>points</Text>
          </View>
          <Text style={styles.pointsSubtextCentered}>Tap to view your barcode</Text>
        </TouchableOpacity>

        {punchCards.length > 0 && (
          <View style={styles.punchSection}>
            <Text style={styles.sectionTitle}>PUNCH CARDS</Text>
            <ScrollView 
              horizontal 
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.punchScroll}
            >
              {punchCards.map((card) => (
                <View key={card.punchCardId} style={styles.punchCard}>
                  <Text style={styles.punchTitle} numberOfLines={2}>{card.punchCardName.toUpperCase()}</Text>
                  <View style={styles.punchVisual}>
                    {Array.from({ length: Math.min(card.punchesRequired, 6) }).map((_, i) => (
                      <View
                        key={i}
                        style={[
                          styles.punchStar,
                          i < card.currentPunches && styles.punchStarFilled
                        ]}
                      >
                        <Text style={styles.starText}>{i < card.currentPunches ? '★' : '☆'}</Text>
                      </View>
                    ))}
                  </View>
                  <Text style={styles.punchProgress}>
                    {card.currentPunches} of {card.punchesRequired} visits
                  </Text>
                  {card.rewardReady ? (
                    <View style={styles.rewardReady}>
                      <Text style={styles.rewardReadyText}>REWARD READY!</Text>
                    </View>
                  ) : (
                    <Text style={styles.rewardLabel}>{getRewardText(card)}</Text>
                  )}
                </View>
              ))}
            </ScrollView>
          </View>
        )}

        <Text style={styles.sectionTitle}>FEATURED</Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.promoScroll}
        >
          {FEATURED_PROMOTIONS.map((promo) => (
            <View key={promo.id} style={styles.promoCard}>
              <Image
                source={{ uri: promo.image }}
                style={styles.promoImage}
                resizeMode="cover"
              />
              <LinearGradient 
                colors={['transparent', 'rgba(0,0,0,0.85)']} 
                style={styles.promoOverlay}
              >
                <Text style={styles.promoTitle}>{promo.title}</Text>
                <Text style={styles.promoSubtitle}>{promo.subtitle}</Text>
              </LinearGradient>
            </View>
          ))}
        </ScrollView>

        <View style={styles.bottomSpacer} />
      </ScrollView>

      <View style={styles.bottomNav}>
        <TouchableOpacity style={styles.navItem} onPress={() => {}}>
          <Text style={styles.navIconActive}>🏠</Text>
          <Text style={styles.navLabelActive}>Home</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.navItem} onPress={() => router.push('/barcode')}>
          <Text style={styles.navIcon}>📱</Text>
          <Text style={styles.navLabel}>Barcode</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.navItem} onPress={() => router.push('/history')}>
          <Text style={styles.navIcon}>📋</Text>
          <Text style={styles.navLabel}>History</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.navItem} onPress={() => router.push('/profile')}>
          <Text style={styles.navIcon}>👤</Text>
          <Text style={styles.navLabel}>Profile</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

function getGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Morning';
  if (hour < 17) return 'Afternoon';
  return 'Evening';
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 20,
    paddingTop: 8,
  },
  headerBanner: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    marginBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
    marginHorizontal: -20,
    paddingHorizontal: 20,
  },
  menuBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuIcon: {
    fontSize: 24,
    color: '#1E293B',
  },
  headerLogo: {
    width: 220,
    height: 65,
  },
  locationBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  locationIcon: {
    fontSize: 24,
  },
  greeting: {
    fontSize: 22,
    fontWeight: '800',
    color: '#1E293B',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    textAlign: 'center',
  },
  tagline: {
    fontSize: 14,
    color: '#64748B',
    marginTop: 4,
    marginBottom: 20,
    textAlign: 'center',
  },
  pointsSection: {
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 20,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    marginBottom: 16,
    alignItems: 'center',
  },
  pointsHeader: {
    alignItems: 'center',
    marginBottom: 12,
  },
  pointsLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: '#1E293B',
    letterSpacing: 0.5,
  },
  earnRate: {
    fontSize: 12,
    fontWeight: '600',
    color: '#64748B',
  },
  progressContainer: {
    marginBottom: 14,
  },
  progressBg: {
    height: 10,
    backgroundColor: '#E2E8F0',
    borderRadius: 5,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 5,
  },
  pointsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  pointsInfo: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  pointsBalanceRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'center',
    marginBottom: 8,
  },
  pointsSubtextCentered: {
    fontSize: 14,
    color: '#64748B',
    textAlign: 'center',
  },
  pointsValue: {
    fontSize: 32,
    fontWeight: '800',
    color: '#1E293B',
  },
  pointsUnit: {
    fontSize: 16,
    fontWeight: '600',
    color: '#64748B',
    marginLeft: 6,
  },
  cashValue: {
    fontSize: 14,
    color: '#22C55E',
    fontWeight: '600',
    marginLeft: 8,
  },
  pointsSubtext: {
    fontSize: 14,
    color: '#64748B',
    marginLeft: 8,
  },
  rewardButton: {
    backgroundColor: '#1E3A8A',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 20,
  },
  rewardButtonText: {
    color: '#FFF',
    fontWeight: '700',
    fontSize: 12,
  },
  cashBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ECFDF5',
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  cashIcon: {
    fontSize: 28,
    marginRight: 12,
  },
  cashContent: {
    flex: 1,
  },
  cashTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#065F46',
  },
  cashSubtext: {
    fontSize: 13,
    color: '#047857',
  },
  punchSection: {
    marginBottom: 16,
  },
  punchScroll: {
    paddingRight: 20,
  },
  punchCard: {
    width: 160,
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 14,
    marginRight: 12,
    borderWidth: 1,
    borderColor: '#E2E8F0',
    alignItems: 'center',
  },
  punchTitle: {
    fontSize: 11,
    fontWeight: '700',
    color: '#1E293B',
    textAlign: 'center',
    marginBottom: 10,
    letterSpacing: 0.3,
  },
  punchVisual: {
    flexDirection: 'row',
    gap: 4,
    marginBottom: 8,
  },
  punchStar: {
    width: 22,
    height: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  punchStarFilled: {},
  starText: {
    fontSize: 18,
    color: '#F59E0B',
  },
  punchProgress: {
    fontSize: 11,
    color: '#64748B',
    marginBottom: 6,
  },
  rewardReady: {
    backgroundColor: '#4ECDC4',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
  },
  rewardReadyText: {
    color: '#FFF',
    fontWeight: '700',
    fontSize: 10,
  },
  rewardLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: '#1E3A8A',
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '800',
    color: '#1E293B',
    marginBottom: 12,
    letterSpacing: 0.5,
  },
  promoScroll: {
    paddingBottom: 8,
  },
  promoCard: {
    width: 200,
    height: 240,
    borderRadius: 16,
    marginRight: 12,
    overflow: 'hidden',
    backgroundColor: '#F1F5F9',
  },
  promoImage: {
    width: '100%',
    height: '100%',
    position: 'absolute',
  },
  promoOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: 14,
    paddingTop: 50,
  },
  promoTitle: {
    color: '#FFF',
    fontSize: 24,
    fontWeight: '800',
  },
  promoSubtitle: {
    color: 'rgba(255,255,255,0.9)',
    fontSize: 12,
    marginTop: 2,
  },
  bottomSpacer: {
    height: 100,
  },
  bottomNav: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    backgroundColor: '#FFF',
    paddingTop: 10,
    paddingBottom: 28,
    borderTopWidth: 1,
    borderTopColor: '#E2E8F0',
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
  },
  navIcon: {
    fontSize: 22,
    marginBottom: 2,
  },
  navIconActive: {
    fontSize: 22,
    marginBottom: 2,
  },
  navLabel: {
    fontSize: 10,
    color: '#94A3B8',
  },
  navLabelActive: {
    fontSize: 10,
    color: '#1E3A8A',
    fontWeight: '600',
  },
  drawerContainer: {
    flex: 1,
    flexDirection: 'row',
  },
  drawerOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  drawerContent: {
    width: width * 0.85,
    backgroundColor: '#FFF',
    height: '100%',
    shadowColor: '#000',
    shadowOffset: { width: 4, height: 0 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  drawerSafe: {
    flex: 1,
  },
  drawerHeader: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  drawerClose: {
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
  },
  drawerCloseIcon: {
    fontSize: 24,
    color: '#64748B',
  },
  drawerAccount: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingBottom: 24,
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
  },
  accountIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#F1F5F9',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  accountEmoji: {
    fontSize: 22,
  },
  accountInfo: {
    flex: 1,
  },
  accountTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#1E293B',
    letterSpacing: 0.5,
  },
  accountId: {
    fontSize: 11,
    color: '#64748B',
    marginTop: 2,
  },
  accountIdValue: {
    fontSize: 11,
    color: '#64748B',
  },
  logoutBtnDrawer: {
    borderWidth: 1,
    borderColor: '#1E293B',
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  logoutTextDrawer: {
    fontSize: 12,
    fontWeight: '600',
    color: '#1E293B',
  },
  drawerScroll: {
    flex: 1,
    paddingTop: 16,
  },
  drawerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 20,
  },
  drawerItemIcon: {
    fontSize: 22,
    marginRight: 16,
    width: 28,
  },
  drawerItemText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1E293B',
    letterSpacing: 0.3,
  },
  drawerDivider: {
    height: 1,
    backgroundColor: '#E2E8F0',
    marginVertical: 16,
    marginHorizontal: 20,
  },
  drawerItemSecondary: {
    paddingVertical: 14,
    paddingHorizontal: 20,
  },
  drawerItemTextSecondary: {
    fontSize: 15,
    color: '#1E293B',
  },
});
