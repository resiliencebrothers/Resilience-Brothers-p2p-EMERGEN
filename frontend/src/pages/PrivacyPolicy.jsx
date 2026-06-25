import LegalLayout from "@/pages/LegalLayout";

export default function PrivacyPolicy() {
  return (
    <LegalLayout
      title="Política de Privacidad"
      eyebrow="Privacy"
      lastUpdated="25 de junio de 2026"
    >
      <p>
        En Resilience Brothers respetamos tu privacidad y nos comprometemos a proteger los datos personales que nos confías cuando usas nuestra plataforma de intercambio P2P de criptomonedas y divisas fiat. Esta política explica qué información recopilamos, cómo la usamos, con quién la compartimos y los derechos que tienes sobre ella.
      </p>

      <h2>1. Responsable del tratamiento</h2>
      <p>
        Resilience Brothers (en adelante, &quot;la Plataforma&quot;, &quot;nosotros&quot;) es responsable del tratamiento de tus datos personales. Para cualquier consulta puedes escribirnos a <a href="mailto:notificacionesresiliencebrothe@gmail.com">notificacionesresiliencebrothe@gmail.com</a>.
      </p>

      <h2>2. Datos que recopilamos</h2>
      <h3>2.1 Datos que tú nos proporcionas</h3>
      <ul>
        <li><strong>Cuenta:</strong> nombre, dirección de correo electrónico y foto de perfil (vía Google OAuth o registro por email y contraseña).</li>
        <li><strong>Verificación:</strong> en flujos KYC futuros podríamos solicitar documento de identidad y una selfie. Hoy esta información NO se recopila salvo aviso explícito.</li>
        <li><strong>Operativa:</strong> beneficiario, monedas, monto y método de entrega/recepción de cada orden o retiro.</li>
        <li><strong>Comprobantes:</strong> imágenes de transferencia bancaria o tx-hash de cripto que tú decides subir como prueba de pago.</li>
      </ul>

      <h3>2.2 Datos que recopilamos automáticamente</h3>
      <ul>
        <li>Dirección IP, tipo de navegador, sistema operativo y zona horaria (para seguridad y prevención de fraude).</li>
        <li>Eventos de uso: inicios de sesión, intentos fallidos, cambios de rol o permisos, operaciones aprobadas/rechazadas. Se almacenan en un registro de auditoría.</li>
        <li>Cookies de sesión (`session_token`) imprescindibles para mantenerte autenticado. NO usamos cookies publicitarias.</li>
      </ul>

      <h2>3. Para qué usamos tus datos</h2>
      <ul>
        <li>Para autenticarte y darte acceso a la Plataforma.</li>
        <li>Para procesar tus órdenes de intercambio, retiros y canjes de mercancía.</li>
        <li>Para enviarte notificaciones operativas (confirmación de operación, aprobación o rechazo).</li>
        <li>Para detectar y prevenir fraude, lavado de dinero o uso indebido.</li>
        <li>Para cumplir obligaciones legales o requerimientos de autoridades competentes.</li>
        <li>Para mejorar la Plataforma mediante análisis agregados y anónimos.</li>
      </ul>

      <h2>4. Base legal del tratamiento</h2>
      <p>
        Tratamos tus datos con base en: (a) la <strong>ejecución del contrato</strong> que aceptas al registrarte; (b) tu <strong>consentimiento explícito</strong> para notificaciones push y emails de marketing (revocable en cualquier momento); (c) el <strong>cumplimiento de obligaciones legales</strong> en materia de prevención de fraude y AML; y (d) nuestro <strong>interés legítimo</strong> en mantener la Plataforma segura.
      </p>

      <h2>5. Con quién compartimos tus datos</h2>
      <p>
        No vendemos tus datos a terceros. Compartimos información estrictamente necesaria con los siguientes proveedores que actúan como encargados de tratamiento:
      </p>
      <ul>
        <li><strong>Google LLC</strong> — autenticación OAuth 2.0 (Sign in with Google).</li>
        <li><strong>Resend</strong> — envío de correos transaccionales (verificación de email, recuperación de contraseña, alertas).</li>
        <li><strong>Emergent.sh</strong> — hosting y operación técnica de la Plataforma.</li>
        <li><strong>MongoDB Atlas</strong> — almacenamiento de la base de datos.</li>
      </ul>
      <p>
        Cada uno de estos proveedores cumple estándares internacionales de seguridad (SOC 2, ISO 27001) y opera bajo acuerdos de procesamiento de datos conformes con el RGPD.
      </p>

      <h2>6. Transferencias internacionales</h2>
      <p>
        Nuestros proveedores pueden almacenar y procesar datos fuera de tu país de residencia (principalmente en EE.UU. y la UE). Cuando esto ocurre, garantizamos un nivel de protección equivalente mediante cláusulas contractuales estándar aprobadas por la Comisión Europea.
      </p>

      <h2>7. Tiempo de conservación</h2>
      <ul>
        <li><strong>Datos de cuenta</strong>: mientras tu cuenta esté activa + 5 años por obligaciones AML.</li>
        <li><strong>Registros de operaciones</strong>: 10 años desde la fecha de la operación (requisito legal habitual en servicios financieros).</li>
        <li><strong>Comprobantes</strong>: 5 años tras la última operación a la que pertenezcan.</li>
        <li><strong>Logs técnicos</strong>: 90 días (rotación automática).</li>
      </ul>

      <h2>8. Tus derechos</h2>
      <p>
        Tienes derecho a: <strong>acceso, rectificación, supresión, limitación, portabilidad y oposición</strong> al tratamiento de tus datos. Para ejercerlos, envíanos un correo a <a href="mailto:notificacionesresiliencebrothe@gmail.com">notificacionesresiliencebrothe@gmail.com</a> identificándote claramente. Responderemos en un plazo máximo de 30 días.
      </p>
      <p>
        Si consideras que no hemos respetado tus derechos, puedes presentar una reclamación ante la autoridad de protección de datos de tu país.
      </p>

      <h2>9. Seguridad</h2>
      <p>
        Aplicamos cifrado TLS 1.3 en tránsito, contraseñas hasheadas con bcrypt, sesiones httpOnly, autenticación de dos factores opcional (TOTP) para acciones críticas, segregación de roles, registros de auditoría inmutables y backups encriptados. Ningún sistema es 100% seguro: si detectamos una brecha que pueda afectarte, te lo notificaremos en 72 horas como exige la normativa.
      </p>

      <h2>10. Menores de edad</h2>
      <p>
        La Plataforma está destinada a personas mayores de 18 años. No recopilamos datos a sabiendas de menores. Si descubres que un menor ha registrado una cuenta, contáctanos para eliminarla.
      </p>

      <h2>11. Cambios en esta política</h2>
      <p>
        Podemos actualizar esta política cuando sea necesario por cambios legales o de servicio. La fecha de la última versión aparece arriba. Si los cambios son sustanciales, te avisaremos por email antes de que entren en vigor.
      </p>

      <h2>12. Contacto</h2>
      <p>
        Para cualquier duda sobre esta política o el tratamiento de tus datos: <a href="mailto:notificacionesresiliencebrothe@gmail.com">notificacionesresiliencebrothe@gmail.com</a>
      </p>

      <p className="text-xs text-neutral-500 italic mt-12 border-t border-white/5 pt-6">
        Este texto es una versión inicial generada como plantilla y debe ser revisada y adaptada por un asesor legal cualificado antes de operar en producción regulada, especialmente para cumplir las normativas locales de tu jurisdicción.
      </p>
    </LegalLayout>
  );
}
