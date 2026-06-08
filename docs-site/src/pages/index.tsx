import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';

export default function Home(): JSX.Element {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`Welcome to ${siteConfig.title}`}
      description="From text prompt to physical 3D print — fully local, no cloud.">
      <main style={{display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '4rem'}}>
        <h1>{siteConfig.title}</h1>
        <p>{siteConfig.tagline}</p>
        <Link
          className="button button--secondary button--lg"
          to="/docs/getting-started/installation">
          Get Started
        </Link>
      </main>
    </Layout>
  );
}
