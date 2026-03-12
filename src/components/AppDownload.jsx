import { useEffect, useState } from 'react';

export default function AppDownload() {
  const iosUrl = "https://apps.apple.com/us/app/birdies-rewards/id6757185748";
  const androidUrl = "https://play.google.com/store/apps/details?id=com.birdies.rewards&hl=en_US";
  const [status, setStatus] = useState("Checking your device and sending you to the right app store...");

  useEffect(() => {
    const ua = navigator.userAgent || navigator.vendor || window.opera || '';
    const isAndroid = /Android/i.test(ua);
    const isIOS = /iPhone|iPad|iPod/i.test(ua) ||
                  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    if (isIOS) {
      setStatus('iPhone detected. Opening the App Store...');
      setTimeout(() => { window.location.replace(iosUrl); }, 300);
    } else if (isAndroid) {
      setStatus('Android detected. Opening Google Play...');
      setTimeout(() => { window.location.replace(androidUrl); }, 300);
    } else {
      setStatus('Choose your app store below to download Birdies Rewards.');
    }
  }, []);

  return (
    <div style={{
      margin: 0,
      fontFamily: 'Arial, Helvetica, sans-serif',
      background: 'linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%)',
      display: 'flex',
      minHeight: '100vh',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '24px',
    }}>
      <div style={{
        width: '100%',
        maxWidth: '560px',
        background: 'white',
        borderRadius: '18px',
        boxShadow: '0 12px 30px rgba(0,0,0,.15)',
        padding: '40px 32px',
        textAlign: 'center',
      }}>
        <img 
          src="/assets/birdies-logo.jpg" 
          alt="Birdies" 
          style={{ height: '60px', marginBottom: '10px' }}
          onError={(e) => { e.target.style.display = 'none'; }}
        />
        <h1 style={{ margin: '0 0 12px', fontSize: '28px', color: '#1E3A8A', fontWeight: 'bold' }}>
          Birdies Rewards
        </h1>
        <p style={{ lineHeight: 1.55, color: '#444', fontSize: '16px' }}>
          {status}
        </p>
        <div style={{ display: 'grid', gap: '12px', marginTop: '24px' }}>
          <a
            href={iosUrl}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '12px',
              padding: '16px 18px',
              borderRadius: '12px',
              textDecoration: 'none',
              fontWeight: 700,
              background: '#000',
              color: 'white',
              fontSize: '16px',
            }}
          >
            <img 
              src="https://developer.apple.com/assets/elements/badges/download-on-the-app-store.svg"
              alt="App Store"
              style={{ height: '30px' }}
            />
            Download for iPhone
          </a>
          <a
            href={androidUrl}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '12px',
              padding: '16px 18px',
              borderRadius: '12px',
              textDecoration: 'none',
              fontWeight: 700,
              background: '#01875f',
              color: 'white',
              fontSize: '16px',
            }}
          >
            <img 
              src="https://play.google.com/intl/en_us/badges/static/images/badges/en_badge_web_generic.png"
              alt="Google Play"
              style={{ height: '40px' }}
            />
            Download for Android
          </a>
        </div>
        <p style={{ fontSize: '14px', color: '#666', marginTop: '16px' }}>
          If nothing happens automatically, tap the button for your device.
        </p>
      </div>
    </div>
  );
}
