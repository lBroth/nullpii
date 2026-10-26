// SPDX-License-Identifier: Apache-2.0
//
// The default theme, plus the home page's custom sections and the few
// rules the included READMEs need. Everything rides on the home
// layout's slots, so it renders only on the home page: the parallax
// backdrop behind everything, the flow diagram under the hero, the
// feature grid (it carries its own SVG icons, which the frontmatter
// cannot), and the install snippet at the bottom.

import DefaultTheme from 'vitepress/theme';
import { type FunctionalComponent, h } from 'vue';
import FeaturesGrid from './components/FeaturesGrid.vue';
import HomeBackdrop from './components/HomeBackdrop.vue';
import HowItWorks from './components/HowItWorks.vue';
import InstallSection from './components/InstallSection.vue';
import './custom.css';

const Layout: FunctionalComponent = () =>
  h(DefaultTheme.Layout, null, {
    'home-hero-before': () => h(HomeBackdrop),
    'home-hero-after': () => h(HowItWorks),
    'home-features-before': () => h(FeaturesGrid),
    'home-features-after': () => h(InstallSection),
  });

export default {
  ...DefaultTheme,
  Layout,
};
