import { useEffect, useState, useCallback } from 'react';
import { router, useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Alert,
  RefreshControl,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, Spacing, FontSize, BorderRadius, Shadows } from '../constants/theme';
import { API_BASE_URL } from '../constants/api';

interface Customer {
  id: number;
  firstName: string;
  lastName: string;
  phone: string;
  email?: string;
  loyaltyId: string;
  pointsBalance: number;
  dateOfBirth?: string;
  createdAt?: string;
}

export default function ProfileScreen() {
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useFocusEffect(
    useCallback(() => {
      loadCustomer();
    }, [])
  );

  const loadCustomer = async () => {
    try {
      const stored = await AsyncStorage.getItem('customer');
      if (!stored) return;

      const cust = JSON.parse(stored);
      setCustomer(cust);

      const response = await fetch(`${API_BASE_URL}/api/pos/customer-lookup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: cust.phone }),
      });

      if (response.ok) {
        const data = await response.json();
        const updatedCustomer = {
          ...cust,
          pointsBalance: data.pointsBalance || 0,
          firstName: data.firstName || cust.firstName,
          lastName: data.lastName || cust.lastName,
          loyaltyId: data.loyaltyId || cust.loyaltyId,
          email: data.email || cust.email,
          dateOfBirth: data.dateOfBirth || cust.dateOfBirth,
        };
        setCustomer(updatedCustomer);
        await AsyncStorage.setItem('customer', JSON.stringify(updatedCustomer));
      }
    } catch (err) {
      console.log('Error loading customer:', err);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadCustomer();
    setRefreshing(false);
  };

  const formatPhone = (phone: string) => {
    const digits = phone.replace(/\D/g, '');
    if (digits.length === 10) {
      return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
    }
    return phone;
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return 'Not set';
    // Parse as local date to avoid timezone shift
    // Date format is YYYY-MM-DD from database
    const parts = dateStr.split('T')[0].split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0]);
      const month = parseInt(parts[1]) - 1; // JS months are 0-indexed
      const day = parseInt(parts[2]);
      const date = new Date(year, month, day);
      return date.toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      });
    }
    return dateStr;
  };

  const getMemberSince = () => {
    if (!customer?.createdAt) return 'Member';
    const date = new Date(customer.createdAt);
    return `Member since ${date.toLocaleDateString('en-US', {
      month: 'short',
      year: 'numeric',
    })}`;
  };

  const handleLogout = () => {
    Alert.alert(
      'Sign Out',
      'Are you sure you want to sign out?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign Out',
          style: 'destructive',
          onPress: async () => {
            await AsyncStorage.removeItem('customer');
            router.replace('/');
          },
        },
      ]
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Profile</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.primary} />
        }
      >
        <LinearGradient colors={Colors.gradient.primary} style={styles.profileCard}>
          <View style={styles.avatarContainer}>
            <Text style={styles.avatarText}>
              {customer?.firstName?.[0]?.toUpperCase() || '?'}
              {customer?.lastName?.[0]?.toUpperCase() || ''}
            </Text>
          </View>
          <Text style={styles.profileName}>
            {customer?.firstName} {customer?.lastName}
          </Text>
          <Text style={styles.memberSince}>{getMemberSince()}</Text>
        </LinearGradient>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Account Information</Text>

          <View style={styles.infoCard}>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Phone</Text>
              <Text style={styles.infoValue}>
                {customer?.phone ? formatPhone(customer.phone) : 'Not set'}
              </Text>
            </View>

            <View style={styles.divider} />

            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Email</Text>
              <Text style={styles.infoValue}>
                {customer?.email || 'Not set'}
              </Text>
            </View>

            <View style={styles.divider} />

            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Birthday</Text>
              <Text style={styles.infoValue}>
                {formatDate(customer?.dateOfBirth)}
              </Text>
            </View>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Loyalty Card</Text>

          <View style={styles.infoCard}>
            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Loyalty ID</Text>
              <Text style={[styles.infoValue, styles.monoText]}>
                {customer?.loyaltyId || 'N/A'}
              </Text>
            </View>

            <View style={styles.divider} />

            <View style={styles.infoRow}>
              <Text style={styles.infoLabel}>Points Balance</Text>
              <Text style={[styles.infoValue, styles.pointsText]}>
                {customer?.pointsBalance?.toLocaleString() || 0} pts
              </Text>
            </View>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>How Points Work</Text>

          <View style={styles.infoCard}>
            <View style={styles.howItWorksRow}>
              <View style={styles.howItWorksIcon}>
                <Text style={styles.iconText}>🛒</Text>
              </View>
              <View style={styles.howItWorksContent}>
                <Text style={styles.howItWorksTitle}>Earn Points</Text>
                <Text style={styles.howItWorksDesc}>
                  Get 5 points for every $1 you spend
                </Text>
              </View>
            </View>

            <View style={styles.divider} />

            <View style={styles.howItWorksRow}>
              <View style={styles.howItWorksIcon}>
                <Text style={styles.iconText}>🎁</Text>
              </View>
              <View style={styles.howItWorksContent}>
                <Text style={styles.howItWorksTitle}>Redeem Rewards</Text>
                <Text style={styles.howItWorksDesc}>
                  100 points = $1.00 off your purchase
                </Text>
              </View>
            </View>
          </View>
        </View>

        <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
          <Text style={styles.logoutText}>Sign Out</Text>
        </TouchableOpacity>

        <Text style={styles.version}>Birdies Rewards v1.0.0</Text>
      </ScrollView>
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
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: Spacing.lg,
    paddingBottom: Spacing.xxl,
  },
  profileCard: {
    borderRadius: BorderRadius.xl,
    padding: Spacing.xl,
    alignItems: 'center',
    marginBottom: Spacing.xl,
    ...Shadows.lg,
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: Spacing.md,
  },
  avatarText: {
    fontSize: FontSize.xxl,
    fontWeight: '700',
    color: Colors.surface,
  },
  profileName: {
    fontSize: FontSize.xl,
    fontWeight: '700',
    color: Colors.surface,
    marginBottom: Spacing.xs,
  },
  memberSince: {
    fontSize: FontSize.sm,
    color: 'rgba(255, 255, 255, 0.8)',
  },
  section: {
    marginBottom: Spacing.lg,
  },
  sectionTitle: {
    fontSize: FontSize.lg,
    fontWeight: '700',
    color: Colors.text,
    marginBottom: Spacing.md,
  },
  infoCard: {
    backgroundColor: Colors.surface,
    borderRadius: BorderRadius.lg,
    padding: Spacing.lg,
    ...Shadows.sm,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
  },
  infoLabel: {
    fontSize: FontSize.md,
    color: Colors.textSecondary,
  },
  infoValue: {
    fontSize: FontSize.md,
    fontWeight: '600',
    color: Colors.text,
  },
  monoText: {
    fontFamily: 'monospace',
    fontSize: FontSize.sm,
  },
  pointsText: {
    color: Colors.primary,
  },
  divider: {
    height: 1,
    backgroundColor: Colors.border,
    marginVertical: Spacing.xs,
  },
  howItWorksRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
  },
  howItWorksIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.surfaceAlt,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: Spacing.md,
  },
  iconText: {
    fontSize: 20,
  },
  howItWorksContent: {
    flex: 1,
  },
  howItWorksTitle: {
    fontSize: FontSize.md,
    fontWeight: '600',
    color: Colors.text,
    marginBottom: 2,
  },
  howItWorksDesc: {
    fontSize: FontSize.sm,
    color: Colors.textSecondary,
  },
  logoutButton: {
    backgroundColor: Colors.error + '15',
    borderRadius: BorderRadius.md,
    padding: Spacing.lg,
    alignItems: 'center',
    marginTop: Spacing.md,
  },
  logoutText: {
    fontSize: FontSize.md,
    fontWeight: '600',
    color: Colors.error,
  },
  version: {
    textAlign: 'center',
    fontSize: FontSize.sm,
    color: Colors.textLight,
    marginTop: Spacing.lg,
  },
});
