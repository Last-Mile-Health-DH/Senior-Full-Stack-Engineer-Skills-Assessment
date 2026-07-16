"use client";
import { useEffect, useState } from 'react';

export default function HomePage() {
  const [html, setHtml] = useState('Loading...');

  useEffect(() => {
    fetch('http://localhost:6100/', { headers: { Accept: 'text/html' } })
      .then((res) => res.text())
      .then((data) => setHtml(data))
      .catch(() => setHtml('Failed to load home page.'));
  }, []);

  return (
    <div dangerouslySetInnerHTML={{ __html: html }} />
  );
}
