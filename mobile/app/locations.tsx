import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
  Linking,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { API_BASE_URL } from '../constants/api';

interface StoreLocation {
  id: number;
  locationName: string;
  address1: string;
  address2?: string;
  city: string;
  state: string;
  zipCode: string;
  pdiStoreNumber?: string;
}

export default function LocationsScreen() {
  const [locations, setLocations] = useState<StoreLocation[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLocations();
  }, []);

  const loadLocations = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/locations`);
      if (response.ok) {
        const data = await response.json();
        setLocations(data);
      }
    } catch (err) {
      console.log('Error loading locations:', err);
    } finally {
      setLoading(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadLocations();
    setRefreshing(false);
  };

  const openMaps = (location: StoreLocation) => {
    const address = encodeURIComponent(
      `${location.address1}, ${location.city}, ${location.state} ${location.zipCode}`
    );
    const url = Platform.select({
      ios: `maps:0,0?q=${address}`,
      android: `geo:0,0?q=${address}`,
    });
    if (url) {
      Linking.openURL(url);
    }
  };

  const openAllLocationsMap = () => {
    const url = Platform.select({
      ios: `maps:?ll=38.5,-76.8&z=8`,
      android: `geo:38.5,-76.8?z=8`,
    });
    if (url) {
      Linking.openURL(url);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Our Locations</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#1E3A8A" />
        }
        showsVerticalScrollIndicator={false}
      >
        <TouchableOpacity style={styles.heroBanner} onPress={openAllLocationsMap}>
          <Text style={styles.heroIcon}>🗺️</Text>
          <Text style={styles.heroText}>Find a Birdies Near You</Text>
          <Text style={styles.heroSubtext}>
            {locations.length > 0 
              ? `${locations.length} locations • Tap to view on map`
              : 'Loading locations...'}
          </Text>
        </TouchableOpacity>

        <Text style={styles.sectionTitle}>ALL LOCATIONS</Text>

        {loading ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>Loading locations...</Text>
          </View>
        ) : locations.length === 0 ? (
          <View style={styles.loadingCard}>
            <Text style={styles.loadingText}>No locations found</Text>
          </View>
        ) : (
          locations.map((location) => (
            <View key={location.id} style={styles.locationCard}>
              <View style={styles.locationHeader}>
                <View style={styles.storeIcon}>
                  <Text style={styles.storeEmoji}>⛽</Text>
                </View>
                <View style={styles.locationInfo}>
                  <Text style={styles.locationName}>{location.locationName || `Birdies #${location.pdiStoreNumber || location.id}`}</Text>
                  <Text style={styles.locationAddress}>{location.address1}</Text>
                  {location.address2 && <Text style={styles.locationAddress}>{location.address2}</Text>}
                  <Text style={styles.locationCity}>
                    {location.city}{location.state ? `, ${location.state}` : ''} {location.zipCode}
                  </Text>
                </View>
              </View>
              
              <TouchableOpacity 
                style={styles.directionsBtn}
                onPress={() => openMaps(location)}
              >
                <Text style={styles.directionsIcon}>🧭</Text>
                <Text style={styles.directionsText}>Get Directions</Text>
              </TouchableOpacity>
            </View>
          ))
        )}

        <View style={styles.bottomSpacer} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#FFF',
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
  },
  backBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backIcon: {
    fontSize: 28,
    color: '#1E293B',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1E293B',
  },
  placeholder: {
    width: 40,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 16,
  },
  heroBanner: {
    backgroundColor: '#1E3A8A',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    marginBottom: 24,
  },
  heroIcon: {
    fontSize: 40,
    marginBottom: 12,
  },
  heroText: {
    fontSize: 20,
    fontWeight: '700',
    color: '#FFF',
    marginBottom: 4,
  },
  heroSubtext: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.8)',
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: '#64748B',
    letterSpacing: 0.5,
    marginBottom: 12,
  },
  loadingCard: {
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 24,
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 14,
    color: '#64748B',
  },
  locationCard: {
    backgroundColor: '#FFF',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  locationHeader: {
    flexDirection: 'row',
    marginBottom: 14,
  },
  storeIcon: {
    width: 48,
    height: 48,
    backgroundColor: '#EEF2FF',
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  storeEmoji: {
    fontSize: 24,
  },
  locationInfo: {
    flex: 1,
  },
  locationName: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1E293B',
    marginBottom: 4,
  },
  locationAddress: {
    fontSize: 14,
    color: '#64748B',
  },
  locationCity: {
    fontSize: 14,
    color: '#64748B',
  },
  directionsBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1E3A8A',
    paddingVertical: 12,
    borderRadius: 8,
  },
  directionsIcon: {
    fontSize: 18,
    marginRight: 8,
  },
  directionsText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFF',
  },
  bottomSpacer: {
    height: 20,
  },
});
