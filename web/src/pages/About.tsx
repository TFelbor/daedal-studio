import { Blueprint } from '../components/Blueprint';
import { useTheme } from '../hooks/useTheme';
import emblemOnDark from '../assets/funded_by_eu-dark.png';
import emblemOnLight from '../assets/funded_by_eu-light.png';
import lockupOnDark from '../assets/eit_dgtl_banner-dark.png';
import lockupOnLight from '../assets/eit_dgtl_banner-light.png';
import styles from './About.module.css';

/**
 * Disclaimer C, verbatim — the wording the Prize Agreement's visibility clause asks for
 * (Annex I, MGA Art. 17.2; Rules & Regulations §7.10). It is a quotation, not copy:
 * do not edit it for style, shorten it, or split it. `tests/test_eu_funding_credit.py`
 * compares it character for character.
 */
const EU_DISCLAIMER =
  'Funded by the European Union. Views and opinions expressed are however those of the author(s) only and do not necessarily reflect those of the European Union or 28DIGITAL. Neither the European Union nor 28DIGITAL can be held responsible for them.';

/**
 * The same artwork in two inks, keyed by the ground it sits on. `-dark` has white
 * lettering for the dark ground and `-light` blue lettering for the light one; the flag
 * is identical in both. Swapping the file is the only permitted way to make the emblem
 * work on both grounds — a CSS filter or an opacity would be recolouring it.
 */
const EMBLEM = {
  dark: { src: emblemOnDark, width: 357, height: 108 },
  light: { src: emblemOnLight, width: 370, height: 120 },
} as const;

/** 28DIGITAL's lock-up (element A), in the same two inks and for the same reason. */
const LOCKUP = {
  dark: { src: lockupOnDark, width: 843, height: 142 },
  light: { src: lockupOnLight, width: 843, height: 142 },
} as const;

/**
 * The lock-up's text alternative, and the only place in the app where the EIT is named.
 * "Initiated by the EIT" describes 28DIGITAL and is legitimate only as part of 28DIGITAL's
 * own lock-up — which is what this is the alternative *for*. It must never be lifted into
 * visible copy, least of all under the Daedal Studio name; `tests/test_eu_funding_credit.py`
 * allows the phrase here and nowhere else.
 */
const LOCKUP_ALT = '28DIGITAL — Initiated by the European Institute of Innovation and Technology (EIT)';

/**
 * About and credits.
 *
 * The app is a major result funded by 28DIGITAL's Venture Incubation Program, so it
 * carries element B — the EU emblem with "Funded by the European Union" — and, because
 * this page names the program, disclaimer C beside it. 28DIGITAL's own lock-up (element
 * A) stands next to them — required on the website, carried here by choice so the page
 * credits the program the way the landing page does. The rules are in the landing-page
 * repository (`docs/eu-visibility-rules.md`); three of them shape this file:
 *
 * - **"Funded by", never "Co-funded by".**
 * - **"Initiated by the EIT" describes 28DIGITAL, not us**, and appears only inside
 *   28DIGITAL's lock-up: the artwork, and `LOCKUP_ALT` as its text alternative.
 * - **The emblem stands on its own and is never smaller than a logo beside it.** The
 *   lock-up is 52px tall, so its 28DGTL square (97 % of the artwork's height) stays below
 *   the emblem's flag at 64px (87 % of it on the light file, 96 % on the dark). No Daedal
 *   mark shares this block; the nav wordmark is 26px.
 */
export function About() {
  const theme = useTheme();
  const emblem = EMBLEM[theme];
  const lockup = LOCKUP[theme];

  return (
    <div className="sheet">
      <div className={styles.page}>
        <header className={styles.head}>
          <div className={`eyebrow ${styles.kicker}`}>
            <span className="label-accent">About and credits</span>
          </div>
          <h1 className="display">About</h1>
          <p className={styles.lede}>
            Daedal Studio designs printable organizers for card and board games — deck
            boxes, dividers, token trays and box inserts — sized to what they hold.
          </p>
        </header>

        <section className={styles.section} aria-labelledby="about-funding">
          <h2 id="about-funding" className="subheading">
            Funding
          </h2>
          <Blueprint className={styles.credit}>
            <div className={styles.marks}>
              <img
                className={styles.lockup}
                src={lockup.src}
                width={lockup.width}
                height={lockup.height}
                alt={LOCKUP_ALT}
              />
              <span className={styles.markDivider} aria-hidden="true" />
              <img
                className={styles.emblem}
                src={emblem.src}
                width={emblem.width}
                height={emblem.height}
                alt="Funded by the European Union"
              />
            </div>
            <p className={styles.body}>
              Daedal Studio is funded by the European Union through the Venture Incubation
              Program of 28DIGITAL. This app is part of the work the program funds.
            </p>
            <p className={styles.disclaimer}>{EU_DISCLAIMER}</p>
          </Blueprint>
        </section>
      </div>
    </div>
  );
}
