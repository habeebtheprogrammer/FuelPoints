import { useState } from 'react';

export default function DeleteAccount() {
  const [step, setStep] = useState(1);
  const [phone, setPhone] = useState('');
  const [pin, setPin] = useState('');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [deleted, setDeleted] = useState(false);

  const formatPhone = (value) => {
    const digits = value.replace(/\D/g, '').slice(0, 10);
    if (digits.length <= 3) return digits;
    if (digits.length <= 6) return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  };

  const formatDOB = (value) => {
    const digits = value.replace(/\D/g, '').slice(0, 8);
    if (digits.length <= 2) return digits;
    if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
    return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
  };

  const handleVerify = async () => {
    setError('');
    const phoneDigits = phone.replace(/\D/g, '');
    if (phoneDigits.length !== 10) {
      setError('Please enter a valid 10-digit phone number.');
      return;
    }
    if (!pin || pin.length !== 4) {
      setError('Please enter your 4-digit PIN.');
      return;
    }
    const dobDigits = dateOfBirth.replace(/\D/g, '');
    if (dobDigits.length !== 8) {
      setError('Please enter your date of birth (MM/DD/YYYY).');
      return;
    }

    setLoading(true);
    try {
      const dobFormatted = `${dateOfBirth.slice(6, 10)}-${dateOfBirth.slice(0, 2)}-${dateOfBirth.slice(3, 5)}`;
      const res = await fetch('/api/public/verify-delete-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: phoneDigits, pin, dateOfBirth: dobFormatted }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Verification failed.');
        return;
      }
      setCustomerName(data.customerName);
      setStep(2);
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setError('');
    setLoading(true);
    try {
      const phoneDigits = phone.replace(/\D/g, '');
      const dobFormatted = `${dateOfBirth.slice(6, 10)}-${dateOfBirth.slice(0, 2)}-${dateOfBirth.slice(3, 5)}`;
      const res = await fetch('/api/public/delete-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: phoneDigits, pin, dateOfBirth: dobFormatted }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || 'Deletion failed.');
        return;
      }
      setDeleted(true);
      setStep(3);
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '20px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      <div style={{
        background: 'white',
        borderRadius: '16px',
        padding: '40px',
        maxWidth: '450px',
        width: '100%',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: '30px' }}>
          <h1 style={{ fontSize: '20px', fontWeight: 'bold', color: '#1E3A8A', margin: 0 }}>
            Birdies<span style={{ fontSize: '16px' }}>&#127942;</span>
          </h1>
        </div>

        {step === 1 && (
          <>
            <h2 style={{ textAlign: 'center', color: '#1e293b', fontSize: '22px', margin: '0 0 8px 0' }}>
              Delete Your Account
            </h2>
            <p style={{ textAlign: 'center', color: '#64748b', fontSize: '14px', margin: '0 0 25px 0' }}>
              Please verify your identity to proceed.
            </p>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '6px' }}>
                Phone Number
              </label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(formatPhone(e.target.value))}
                placeholder="(555) 123-4567"
                style={{
                  width: '100%',
                  padding: '12px',
                  border: '1px solid #d1d5db',
                  borderRadius: '8px',
                  fontSize: '15px',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '6px' }}>
                4-Digit PIN
              </label>
              <input
                type="password"
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 4))}
                placeholder="****"
                maxLength={4}
                style={{
                  width: '100%',
                  padding: '12px',
                  border: '1px solid #d1d5db',
                  borderRadius: '8px',
                  fontSize: '15px',
                  boxSizing: 'border-box',
                  letterSpacing: '8px',
                  textAlign: 'center',
                }}
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '6px' }}>
                Date of Birth
              </label>
              <input
                type="text"
                value={dateOfBirth}
                onChange={(e) => setDateOfBirth(formatDOB(e.target.value))}
                placeholder="MM/DD/YYYY"
                style={{
                  width: '100%',
                  padding: '12px',
                  border: '1px solid #d1d5db',
                  borderRadius: '8px',
                  fontSize: '15px',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {error && (
              <div style={{
                background: '#fef2f2',
                border: '1px solid #fecaca',
                borderRadius: '8px',
                padding: '10px 14px',
                color: '#dc2626',
                fontSize: '13px',
                marginBottom: '16px',
              }}>
                {error}
              </div>
            )}

            <button
              onClick={handleVerify}
              disabled={loading}
              style={{
                width: '100%',
                padding: '12px',
                background: loading ? '#94a3b8' : '#dc2626',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                fontSize: '15px',
                fontWeight: '600',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Verifying...' : 'Verify Identity'}
            </button>
          </>
        )}

        {step === 2 && (
          <>
            <h2 style={{ textAlign: 'center', color: '#dc2626', fontSize: '22px', margin: '0 0 16px 0' }}>
              Confirm Account Deletion
            </h2>

            <div style={{
              background: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: '12px',
              padding: '20px',
              marginBottom: '20px',
            }}>
              <p style={{ margin: '0 0 12px 0', fontWeight: '600', color: '#991b1b', fontSize: '15px' }}>
                {customerName}, are you sure?
              </p>
              <p style={{ margin: '0 0 10px 0', color: '#7f1d1d', fontSize: '13px', lineHeight: '1.5' }}>
                This action will permanently delete:
              </p>
              <ul style={{ margin: '0 0 10px 0', paddingLeft: '20px', color: '#7f1d1d', fontSize: '13px', lineHeight: '1.8' }}>
                <li>Your account and profile information</li>
                <li>All loyalty points and rewards balance</li>
                <li>Transaction and purchase history</li>
                <li>Punch card progress and history</li>
              </ul>
              <p style={{
                margin: 0,
                color: '#991b1b',
                fontSize: '13px',
                fontWeight: '700',
              }}>
                This cannot be undone. Your data cannot be retrieved after deletion.
              </p>
            </div>

            {error && (
              <div style={{
                background: '#fef2f2',
                border: '1px solid #fecaca',
                borderRadius: '8px',
                padding: '10px 14px',
                color: '#dc2626',
                fontSize: '13px',
                marginBottom: '16px',
              }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                onClick={() => { setStep(1); setError(''); }}
                style={{
                  flex: 1,
                  padding: '12px',
                  background: '#f1f5f9',
                  color: '#475569',
                  border: '1px solid #cbd5e1',
                  borderRadius: '8px',
                  fontSize: '15px',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={loading}
                style={{
                  flex: 1,
                  padding: '12px',
                  background: loading ? '#94a3b8' : '#dc2626',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  fontSize: '15px',
                  fontWeight: '600',
                  cursor: loading ? 'not-allowed' : 'pointer',
                }}
              >
                {loading ? 'Deleting...' : 'Delete My Account'}
              </button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>&#10003;</div>
              <h2 style={{ color: '#16a34a', fontSize: '22px', margin: '0 0 12px 0' }}>
                Account Deleted
              </h2>
              <p style={{ color: '#64748b', fontSize: '14px', lineHeight: '1.6' }}>
                Your Birdies Rewards account has been permanently deleted.
                All associated data has been removed from our systems.
              </p>
              <p style={{ color: '#64748b', fontSize: '13px', marginTop: '16px' }}>
                You can close this page now.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
