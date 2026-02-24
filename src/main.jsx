import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import App from './App';
import Signup from './components/Signup';
import ResetPassword from './components/ResetPassword';
import JobApplication711 from './components/JobApplication711';
import JobApplicationQR from './components/JobApplicationQR';
import AppStoreQR from './components/AppStoreQR';
import DeleteAccount from './components/DeleteAccount';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/signup" element={<Signup />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/apply/7-11" element={<JobApplication711 />} />
        <Route path="/qr/7-11" element={<JobApplicationQR />} />
        <Route path="/qr/app" element={<AppStoreQR />} />
        <Route path="/delete-account" element={<DeleteAccount />} />
        <Route path="/*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
