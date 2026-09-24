"""Frequent given names and surnames in Spain (incl. Galician, Catalan, Basque).

Support data for the rules; the AI model (GLiNER) handles names outside these lists.
Entries are lowercase without accents.
"""
import unicodedata


def _norm(words: str) -> frozenset[str]:
    out = set()
    for word in words.split():
        out.add("".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn"))
    return frozenset(out)


FIRST_NAMES = _norm("""
aaron abel abraham ada adela adelaida adolfo adoracion adria adrian adriana africa agata agueda agustin agustina aida
ainara ainhoa aitana aitor aitziber alazne alba alberto albert alejandra alejandro alex alexandra alexander alexis alfonso
alfredo alicia alma almudena alonso alvaro amaia amalia amador amparo ana anabel anastasio andoni andrea andres andreu
angel angela angeles angelina angustias anna anselmo antonia antonio antxon aranzazu araceli arantxa ariadna ariel
armando arnau arturo ascension asier asuncion aurelio aurora avelino azucena bartolome basilio baltasar beatriz begona
belen benedicta benigno benito benjamin bernabe bernardo berta blanca borja brais brenda bruno camila camilo candela
candido carina carla carles carlos carlota carmelo carmen carolina casimiro catalina cayetano cecilia celestino celia
cesar chema christian cintia ciro clara claudia claudio clemente concepcion conchita consuelo constantino cristian
cristina cristobal cruz dalia damian dana daniel daniela dario david debora delfina demetrio desiree diana diego dimas
dionisio dolores dominga domingo edgar edgardo eduardo eladio elena eleuterio elias elisa elisabet eloy elsa elvira
emilia emiliano emilio encarnacion endika enric enrique enriqueta erik ernesto esperanza esteban estefania estela
esther estibaliz eugenia eugenio eulalia eusebio eva evaristo ezequiel fabian fabiola facundo fatima federico felicidad
felipe felix fermin fernanda fernando fidel filomena flor flora florencia florencio francesc francisca francisco
francisco-javier fulgencio gabino gabriel gabriela gaizka garazi gema gemma genaro gerard gerardo german gil gines
gisela gloria gonzalo gorka gracia graciela gregorio guadalupe guillem guillermo gustavo hector helena heriberto hernan
herminia hilario hortensia hugo humberto ibai ignacio igor iker ildefonso imanol inmaculada ines ingrid inigo irene
iria iris irune isaac isabel isaias isidro ismael itziar ivan izan jacinto jacobo jaime jan javier jenifer jeronimo
jesus joan joaquim joaquin joel jon jonatan jordi jorge josa jose josefa josefina josep josu juan juana julen julia
julian juliana julio justo karim karina kevin lara laia laura lazaro leandro leire leo leocadia leon leonardo leonor
leticia lidia lilian lluis lola lorena lorenzo lourdes lucas lucia luciano lucrecia luis luisa luna macarena magdalena
maialen maite manel manuel manuela mar marc marcelino marcelo marcial marcos margarita maria mariano marina mario marta
martin martina mateo matias maximino maximo mehdi melania mercedes merce miguel mikel milagros miquel mireia miriam
modesto moises monica montserrat nadia nahia natalia natividad nazaret nekane nerea nestor nicanor nicolas nieves
noa noe noelia nora norberto norma nuria octavio olaia olga oliver olivia omar oriol oscar osvaldo pablo paco paloma
paola pascual patricia patricio pau paula paz pedro pepe pere perla petra pilar placido pol prudencio purificacion
quim quintin rafael rafaela ramiro ramon raquel raul rebeca rebecca regina reinaldo remedios renata ricard ricardo
rigoberto roberta roberto rocio rodrigo rogelio rolando roman romina rosa rosalia rosana rosario roser rosendo roxana
ruben rufino ruth sabina salome salvador samanta samuel sancho sandra santiago sara saul sebastian segismundo serafin
sergi sergio severino silvia simon sofia soledad sonia susana tamara tania tatiana telmo teodora teodoro teresa tomas
tomasa trinidad txema ulises unai urko uxia valentin valentina valeria vanesa vanessa vicenta vicente victor victoria
violeta virginia vladimir waldo wenceslao xabier xavi xavier xoan xose xurxo yago yaiza yasmina yolanda yosune zaida
zoe zuriñe
""")

SURNAMES = _norm("""
abad abellan abril acosta acuña adrover agudo aguilar aguilera aguirre alarcon alba alcaide alcala alcantara alcaraz
alegre alfaro almagro almeida alonso alvarez alvarado amador amat amor andres andreu anton antunez aparicio aragon
aranda arcos arenas arevalo arias ariza arnau arranz arroyo arteaga asensio avila ayala aznar badia baena baeza
bailon ballesteros balaguer baños barba barbero barcelo barragan barrera barrios barroso bartolome bastida batista
bautista bejarano bellido belmonte beltran benavente benavides benitez benito bermejo bermudez bernal blanco blasco
blazquez bonilla bosch bravo brea briones bueno burgos bustos caballero cabello cabezas cabrera cáceres cadenas
calderon calvo camacho campos camps canal cano cantero carbonell cardenas cardona carmona carrasco carrera carretero
carrillo carrion casado casanova casas castaño castellano castillo castro catalan cazorla cebrian cerdan cerezo
cervera chacon chaves cid cisneros clemente cobo collado conde contreras corral correa cortes cortina costa crespo
cruz cuadrado cuenca cuesta cuevas dalmau davila delgado diaz diez dominguez duran echeverria egea elias escobar
escribano escudero espejo esteban esteve estevez exposito fajardo feijoo feliu fernandez ferrandiz ferrer ferreira
ferreiro figueroa flores fonseca font fraga franco frias fuentes gallardo gallego galan galindo galvez gamez garces
garcia garrido gasca gavilan gil gimenez giner godoy gomez gonzalez gordillo gracia granados guerra guerrero guillen
gutierrez guzman haro heredia hernandez hernando herranz herrera herrero hidalgo hierro hurtado ibañez iglesias
infante iniesta izquierdo jaen jimenez jorge jover juan julia jurado lago lamas lara larrañaga lazaro leal ledesma
leiva leon lillo linares llorente lopez lorenzo losada lozano lucas lucena luna luque macias madrid maldonado mancebo
manzano marco marcos marin marquez marti martin martinez mas mata mateo mateos matias medina mejias melero mendez
mendoza menendez mercader merino mesa miguel mir miranda molina moles monroy montero montes montoya mora moral morales
moreno morillo moya muñoz murillo naranjo navarro nieto noguera novoa nuñez ochoa olivares olmedo olmo ordoñez orozco
ortega ortiz otero pacheco padilla pagan palacios palma palomino palomo pardo paredes parra pascual pastor paz pedraza
pedrosa peinado pelaez peña peral perales perez pineda piñeiro pinto pizarro pla plaza polo pons porras portillo
pozo prado prieto puig pujol quesada quintana quintero quiroga ramirez ramos real rebollo redondo reina rey reyes
rial riera rincon rios rivas rivera robles roca rodrigo rodriguez rojas roldan roman romera romero rosa rosado
rosales rovira rubio rueda ruiz saez salas salazar salcedo salgado salinas salvador sanchez sancho sandoval sanjuan
santamaria santana santiago santos sanz sastre segura sepulveda serna serra serrano sevilla sierra silva simon soler
solis soriano sosa sotelo soto suarez taboada tapia tejada tejero tello tena tomas toledo torres tortosa tovar trigo
trujillo urrutia valdes valencia valero valle vallejo valverde varela vargas vazquez vega vela velasco velazquez
ventura vera vicente vidal viera vila vilar villa villalba villanueva villar vives yañez zamora zapata zubiri
etxeberria goikoetxea agirre zabala arrieta garmendia elorza aranburu uriarte bilbao lasa otegi iturbe mendizabal
castelao rivas outeiro rego fernandez-castro teixeira vilas souto pazos pereira lema varela bouzas couto seoane
carballo lorenzo figueira rodil
""")
