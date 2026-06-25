import LegalLayout from "@/pages/LegalLayout";

export default function TermsOfService() {
  return (
    <LegalLayout
      title="Condiciones del Servicio"
      eyebrow="Terms"
      lastUpdated="25 de junio de 2026"
    >
      <p>
        Bienvenido a Resilience Brothers. Al crear una cuenta o utilizar nuestra Plataforma aceptas estas Condiciones del Servicio. Léelas con atención: definen tus derechos y obligaciones, los nuestros y los límites de nuestra responsabilidad.
      </p>

      <h2>1. Definiciones</h2>
      <ul>
        <li><strong>Plataforma</strong>: el sitio web y la aplicación accesibles desde <a href="https://p2p.resiliencebrothers.com">p2p.resiliencebrothers.com</a>.</li>
        <li><strong>Usuario</strong>: cualquier persona física mayor de 18 años que se registre y opere en la Plataforma.</li>
        <li><strong>Operación</strong>: cualquier intercambio entre divisas fiat, criptomonedas o mercancías facilitado a través de la Plataforma.</li>
        <li><strong>Comprobante</strong>: imagen u otro archivo que el Usuario sube como evidencia de un pago o transferencia.</li>
      </ul>

      <h2>2. Naturaleza del servicio</h2>
      <p>
        Resilience Brothers actúa como <strong>facilitador de intercambios P2P</strong> entre Usuarios. NO somos un banco, casa de cambio regulada, exchange centralizado ni custodio de fondos en blockchain. Cada Operación se ejecuta mediante un proceso manual de validación con aprobación humana por parte del equipo administrativo.
      </p>

      <h2>3. Registro y cuenta</h2>
      <ul>
        <li>Para usar la Plataforma debes registrarte aportando información veraz, exacta y actualizada.</li>
        <li>Eres único responsable de la confidencialidad de tu contraseña y de cualquier actividad realizada en tu cuenta.</li>
        <li>Te comprometes a notificarnos de inmediato cualquier uso no autorizado a través de <a href="mailto:notificacionesresiliencebrothe@gmail.com">notificacionesresiliencebrothe@gmail.com</a>.</li>
        <li>No puedes ceder ni compartir tu cuenta con terceros.</li>
      </ul>

      <h2>4. Operaciones</h2>
      <ul>
        <li>Para crear una orden debes seleccionar moneda origen, moneda destino, monto, método de entrega y subir un comprobante de pago.</li>
        <li>Las órdenes pasan por un estado <em>Pendiente → Confirmado o Rechazado</em>. Los plazos típicos son de minutos a 24 horas hábiles.</li>
        <li>Las tasas mostradas en la Plataforma son las vigentes al momento de crear la orden y pueden diferir entre clientes Normales y VIP.</li>
        <li>Una vez Confirmada, una Operación es irreversible salvo causa de fuerza mayor o error manifiesto detectado por la Plataforma.</li>
        <li>Nos reservamos el derecho de rechazar Operaciones cuando: el comprobante no sea válido, exista sospecha de fraude, o el Usuario incumpla estas condiciones.</li>
      </ul>

      <h2>5. Tarifas y tasas de cambio</h2>
      <ul>
        <li>La Plataforma puede aplicar un margen sobre la tasa de mercado, diferenciado entre clientes Normales y clientes VIP.</li>
        <li>NO cobramos una comisión fija adicional al momento de redactar este documento, pero podríamos hacerlo en el futuro previa notificación al Usuario.</li>
        <li>Cualquier tarifa adicional cobrada por terceros (bancos, redes blockchain, gateways) corre por cuenta del Usuario.</li>
      </ul>

      <h2>6. Mercado / canje por mercancías</h2>
      <p>
        La sección de Mercado permite canjear tu saldo VIP por productos físicos disponibles en catálogo. La disponibilidad, precio y costos de envío se muestran al momento del canje. La Plataforma no se hace responsable de eventos posteriores a la entrega (calidad subjetiva del producto, vida útil, etc.) salvo defectos manifiestos reportados en las 48 horas siguientes a la recepción.
      </p>

      <h2>7. Obligaciones del Usuario</h2>
      <p>El Usuario se compromete a:</p>
      <ul>
        <li>Usar la Plataforma únicamente para fines lícitos.</li>
        <li>No utilizar la Plataforma para lavado de dinero, financiación del terrorismo, fraude, evasión fiscal ni ninguna otra actividad ilegal.</li>
        <li>No subir comprobantes falsificados, manipulados o que pertenezcan a terceros sin autorización.</li>
        <li>No intentar acceder a cuentas ajenas, manipular precios, explotar vulnerabilidades o degradar el servicio.</li>
        <li>Cumplir las leyes fiscales y declarar las ganancias que correspondan en su jurisdicción.</li>
      </ul>

      <h2>8. Restricciones geográficas</h2>
      <p>
        La Plataforma puede no estar disponible o estar restringida en ciertos países por razones legales o de cumplimiento. Es responsabilidad del Usuario verificar que su uso es legal en su jurisdicción.
      </p>

      <h2>9. Suspensión y cierre de cuenta</h2>
      <p>
        Podemos suspender o cerrar tu cuenta, congelar saldos pendientes o rechazar Operaciones cuando detectemos: incumplimiento de estas condiciones, actividad sospechosa, requerimiento de autoridad competente, o por motivos técnicos justificados. En caso de cierre, te avisaremos por email y devolveremos cualquier saldo no comprometido siguiendo los procedimientos legales aplicables.
      </p>

      <h2>10. Propiedad intelectual</h2>
      <p>
        Todos los derechos sobre la marca, logos, código, diseño, contenidos y materiales de la Plataforma pertenecen a Resilience Brothers o sus licenciantes. No se concede al Usuario ninguna licencia más allá del uso personal y no comercial del servicio.
      </p>

      <h2>11. Limitación de responsabilidad</h2>
      <p>
        En la máxima medida permitida por la ley, NO seremos responsables de:
      </p>
      <ul>
        <li>Pérdidas indirectas, lucro cesante, daño moral o reputacional.</li>
        <li>Fallos de proveedores externos (bancos, redes blockchain, gateways).</li>
        <li>Errores en datos proporcionados por el Usuario.</li>
        <li>Caídas de servicio causadas por mantenimiento, ataques, fuerza mayor o eventos fuera de nuestro control razonable.</li>
        <li>Pérdidas por volatilidad de precios cripto/fiat entre el momento de crear y de Confirmar una Operación.</li>
      </ul>
      <p>
        Nuestra responsabilidad total agregada hacia un Usuario, por cualquier concepto, queda limitada al monto neto de Operaciones realizadas por ese Usuario en los 12 meses anteriores al evento que motive la reclamación.
      </p>

      <h2>12. Indemnidad</h2>
      <p>
        El Usuario se obliga a mantener indemne a Resilience Brothers frente a cualquier reclamación de terceros derivada del uso indebido de la Plataforma, violación de estas condiciones o infracción de leyes aplicables.
      </p>

      <h2>13. Modificaciones del servicio y de estas condiciones</h2>
      <p>
        Podemos modificar la Plataforma, sus funcionalidades, tarifas y estas condiciones por motivos comerciales, técnicos o legales. Te notificaremos los cambios sustanciales por email con al menos 15 días de antelación. El uso continuado de la Plataforma tras la fecha de entrada en vigor se entenderá como aceptación de las nuevas condiciones.
      </p>

      <h2>14. Ley aplicable y jurisdicción</h2>
      <p>
        Estas condiciones se rigen por la ley aplicable al domicilio de Resilience Brothers. Cualquier controversia se someterá a los tribunales competentes de dicho domicilio, salvo que la normativa imperativa del país de residencia del Usuario disponga otra cosa.
      </p>

      <h2>15. Contacto</h2>
      <p>
        Para cualquier consulta sobre estas condiciones: <a href="mailto:notificacionesresiliencebrothe@gmail.com">notificacionesresiliencebrothe@gmail.com</a>
      </p>

      <p className="text-xs text-neutral-500 italic mt-12 border-t border-white/5 pt-6">
        Este texto es una versión inicial generada como plantilla y debe ser revisada y adaptada por un asesor legal cualificado antes de operar en producción regulada, especialmente para cumplir las normativas locales de tu jurisdicción y los requisitos KYC/AML aplicables a servicios cripto/fiat.
      </p>
    </LegalLayout>
  );
}
