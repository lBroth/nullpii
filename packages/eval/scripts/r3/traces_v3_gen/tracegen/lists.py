# SPDX-License-Identifier: Apache-2.0
"""Name, place and vocabulary lists written by the generator's author from
general knowledge (no external file, no PII dataset, no fake-data library).
City coordinates are rounded public facts; postcode ranges and dialling
prefixes follow the public national numbering conventions."""

from __future__ import annotations

LOCALES = ("en_US", "en_GB", "it_IT", "de_DE", "fr_FR", "es_ES", "nl_NL", "pt_PT", "pl_PL")

GIVEN_F = {
    "en_US": "Emily Sarah Jessica Ashley Jennifer Amanda Megan Lauren Rachel Hannah Olivia Madison Abigail Brittany "
             "Samantha Rebecca Kayla Morgan Taylor Courtney Danielle Natalie Allison Heather Stephanie Kimberly "
             "Michelle Erin Kelsey Alexis Dana Monica Tamika Keisha Priya".split(),
    "en_GB": "Charlotte Sophie Emma Lucy Amelia Chloe Grace Holly Ellie Jessica Hannah Katie Olivia Bethany Georgia "
             "Megan Abigail Freya Isla Poppy Harriet Imogen Eleanor Rosie Zara Niamh Siobhan Fiona Gemma Kirsty "
             "Aisha Rhiannon".split(),
    "it_IT": "Giulia Francesca Chiara Sara Martina Valentina Alessia Federica Elisa Silvia Elena Laura Paola Roberta "
             "Alice Giorgia Anna Beatrice Camilla Ilaria Serena Veronica Marta Noemi Arianna Michela Simona Cristina "
             "Lucia Benedetta Rosaria Nicoletta".split(),
    "de_DE": "Anna Lena Laura Julia Sarah Lisa Katharina Johanna Sophie Marie Hannah Leonie Lea Carolin Franziska "
             "Theresa Miriam Jana Nina Sabine Petra Claudia Stefanie Anja Melanie Kerstin Ute Birgit Annika Jule "
             "Gesa Wiebke".split(),
    "fr_FR": "Camille Léa Manon Chloé Emma Inès Sarah Julie Pauline Marine Laura Céline Mathilde Clémence Élise "
             "Juliette Margaux Anaïs Charlotte Lucie Amandine Audrey Aurélie Sophie Nathalie Isabelle Sandrine "
             "Valérie Hélène Océane Gwenaëlle Maëlle".split(),
    "es_ES": "María Lucía Paula Laura Marta Andrea Sara Carmen Ana Elena Cristina Irene Alba Claudia Raquel Nuria "
             "Silvia Beatriz Patricia Rocío Pilar Inés Noelia Sonia Lorena Alicia Natalia Eva Julia Marina Ainhoa "
             "Montserrat".split(),
    "nl_NL": "Emma Sophie Julia Lisa Anouk Sanne Fleur Lotte Eva Iris Femke Lieke Noor Sara Esther Marloes Inge "
             "Mirjam Annelies Ilse Maaike Roos Floor Tessa Laura Daphne Ingrid Wendy Karin Marieke".split(),
    "pt_PT": "Maria Ana Beatriz Inês Mariana Leonor Carolina Matilde Joana Sofia Catarina Rita Marta Sara Filipa "
             "Patrícia Teresa Raquel Cláudia Sónia Helena Vera Diana Daniela Andreia Bárbara Margarida Rosa Lúcia "
             "Mafalda".split(),
    "pl_PL": "Anna Maria Katarzyna Małgorzata Agnieszka Barbara Ewa Krystyna Magdalena Joanna Aleksandra Monika "
             "Natalia Karolina Paulina Justyna Marta Beata Dorota Weronika Zuzanna Julia Zofia Oliwia Wiktoria "
             "Kinga Iwona Aneta Sylwia Patrycja".split(),
}

GIVEN_M = {
    "en_US": "Michael Christopher Matthew Joshua David Daniel James Andrew Ryan Tyler Brandon Justin Kevin Jason "
             "Eric Brian Kyle Nathan Aaron Zachary Jacob Ethan Logan Austin Dylan Cody Travis Derek Marcus Trevor "
             "DeShawn Raj Hector".split(),
    "en_GB": "Oliver Harry George Jack Thomas James William Charlie Alfie Joshua Samuel Daniel Callum Rhys Owen "
             "Liam Connor Lewis Jamie Euan Hamish Ben Toby Max Archie Freddie Rory Declan Gareth Dominic Imran "
             "Kwame".split(),
    "it_IT": "Marco Alessandro Andrea Luca Matteo Francesco Lorenzo Davide Simone Federico Riccardo Stefano "
             "Giuseppe Antonio Giovanni Paolo Roberto Fabio Daniele Michele Tommaso Nicola Emanuele Gabriele "
             "Filippo Pietro Leonardo Claudio Massimo Salvatore Ettore Gianluca".split(),
    "de_DE": "Lukas Jonas Felix Maximilian Leon Paul Tobias Jan Florian Sebastian Niklas Philipp Moritz Tim Fabian "
             "Simon Stefan Matthias Thomas Andreas Michael Christian Markus Jörg Uwe Dirk Kai Benedikt Henrik "
             "Malte Detlef Torsten".split(),
    "fr_FR": "Lucas Hugo Louis Thomas Nicolas Julien Antoine Maxime Alexandre Romain Mathieu Guillaume Pierre "
             "Clément Quentin Kévin Florian Benjamin Théo Baptiste Sébastien Jérôme François Laurent Olivier "
             "Stéphane Arnaud Yann Gaël Bastien Loïc Hervé".split(),
    "es_ES": "Alejandro Pablo Daniel David Javier Adrián Álvaro Sergio Carlos Hugo Diego Jorge Iván Rubén Raúl "
             "Miguel Manuel Antonio José Francisco Juan Luis Fernando Óscar Íñigo Gonzalo Rodrigo Marcos Víctor "
             "Alberto Jaime Aitor".split(),
    "nl_NL": "Daan Sem Lucas Bram Thijs Jesse Ruben Lars Stijn Niels Jeroen Bas Sander Tim Joost Wouter Pieter Koen "
             "Maarten Thomas Jasper Rik Bart Tom Gijs Mark Erik Dennis Hendrik Willem".split(),
    "pt_PT": "João José António Francisco Pedro Tiago Rui Miguel Duarte Gonçalo Rodrigo Afonso Tomás Diogo Ricardo "
             "Nuno Bruno André Paulo Luís Carlos Hugo Fábio Sérgio Vasco Martim Henrique Filipe Joaquim "
             "Manuel".split(),
    "pl_PL": "Piotr Krzysztof Andrzej Tomasz Paweł Michał Marcin Jakub Adam Łukasz Mateusz Kamil Grzegorz Wojciech "
             "Mariusz Dariusz Rafał Bartosz Szymon Filip Kacper Jan Marek Jacek Damian Sebastian Przemysław Dawid "
             "Artur Robert".split(),
}

FAMILY = {
    "en_US": ["Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
              "Thompson", "White", "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
              "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall",
              "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Patel", "Kim", "Chen", "Okafor", "Sullivan",
              "Smith", "Kowalczyk", "Washington", "Brooks", "Fitzgerald"],
    "en_GB": ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Evans", "Thomas", "Roberts", "Walker",
              "Wright", "Robinson", "Thompson", "White", "Hughes", "Edwards", "Green", "Hall", "Wood", "Harris",
              "Lewis", "Martin", "Jackson", "Clarke", "Turner", "Hill", "Scott", "Cooper", "Morris", "Ward", "Moore",
              "King", "Watson", "Baker", "Harrison", "Morgan", "Patel", "Young", "Allen", "Mitchell", "Anderson",
              "Phillips", "Bell", "Parker", "Davies", "Kaur", "Ahmed", "McDonald", "Campbell", "Stewart", "Murray",
              "O'Brien", "Okonkwo", "Fraser"],
    "it_IT": ["Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci", "Marino", "Greco",
              "Bruno", "Gallo", "Conti", "De Luca", "Mancini", "Costa", "Giordano", "Rizzo", "Lombardi", "Moretti",
              "Barbieri", "Fontana", "Santoro", "Mariani", "Rinaldi", "Caruso", "Ferrara", "Galli", "Martini",
              "Leone", "Longo", "Gentile", "Martinelli", "Vitale", "Lombardo", "Serra", "Coppola", "De Santis",
              "D'Angelo", "Marchetti", "Parisi", "Villa", "Conte", "Ferraro", "Fabbri", "Bianco", "Marini",
              "Grasso", "Valentini", "Messina", "Pellegrini", "Sartori", "Zanetti"],
    "de_DE": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
              "Hoffmann", "Schäfer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz",
              "Zimmermann", "Braun", "Krüger", "Hofmann", "Hartmann", "Lange", "Schmitt", "Werner", "Schmitz",
              "Krause", "Meier", "Lehmann", "Schmid", "Schulze", "Maier", "Köhler", "Herrmann", "König", "Walter",
              "Mayer", "Huber", "Kaiser", "Fuchs", "Peters", "Lang", "Scholz", "Möller", "Weiß", "Jung", "Hahn",
              "Vogel", "Yılmaz", "Öztürk", "Brandt", "Engel"],
    "fr_FR": ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand", "Leroy", "Moreau",
              "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier",
              "Morel", "Girard", "André", "Lefèvre", "Mercier", "Lambert", "Bonnet", "François", "Martinez",
              "Legrand", "Garnier", "Faure", "Rousseau", "Blanc", "Guérin", "Muller", "Henry", "Roussel", "Nicolas",
              "Perrin", "Morin", "Mathieu", "Clément", "Gauthier", "Dumont", "Lopez", "Fontaine", "Chevalier",
              "Robin", "Benali", "Nguyen", "Le Gall", "Kerjean"],
    "es_ES": ["García", "Fernández", "González", "Rodríguez", "López", "Martínez", "Sánchez", "Pérez", "Gómez",
              "Martín", "Jiménez", "Ruiz", "Hernández", "Díaz", "Moreno", "Muñoz", "Álvarez", "Romero", "Alonso",
              "Gutiérrez", "Navarro", "Torres", "Domínguez", "Vázquez", "Ramos", "Gil", "Ramírez", "Serrano",
              "Blanco", "Molina", "Morales", "Suárez", "Ortega", "Delgado", "Castro", "Ortiz", "Rubio", "Marín",
              "Sanz", "Iglesias", "Núñez", "Medina", "Garrido", "Cortés", "Castillo", "Santos", "Lozano",
              "Guerrero", "Cano", "Prieto", "Etxeberria", "Puig"],
    "nl_NL": ["de Jong", "Jansen", "de Vries", "van den Berg", "van Dijk", "Bakker", "Janssen", "Visser", "Smit",
              "Meijer", "de Boer", "Mulder", "de Groot", "Bos", "Vos", "Peters", "Hendriks", "van Leeuwen", "Dekker",
              "Brouwer", "de Wit", "Dijkstra", "Smits", "de Graaf", "van der Meer", "van der Linden", "Kok",
              "Jacobs", "de Haan", "Vermeulen", "van den Heuvel", "van der Veen", "van den Broek", "de Bruijn",
              "van der Heijden", "Schouten", "van Beek", "Willems", "van Vliet", "Hoekstra", "Maas", "Verhoeven",
              "Koster", "Prins", "Blom", "Huisman", "de Leeuw", "Kuipers"],
    "pt_PT": ["Silva", "Santos", "Ferreira", "Pereira", "Oliveira", "Costa", "Rodrigues", "Martins", "Jesus",
              "Sousa", "Fernandes", "Gonçalves", "Gomes", "Lopes", "Marques", "Alves", "Almeida", "Ribeiro", "Pinto",
              "Carvalho", "Teixeira", "Moreira", "Correia", "Mendes", "Nunes", "Soares", "Vieira", "Monteiro",
              "Cardoso", "Rocha", "Neves", "Coelho", "Cruz", "Cunha", "Pires", "Ramos", "Reis", "Simões", "Antunes",
              "Matos", "Fonseca", "Machado", "Araújo", "Barbosa", "Tavares", "Lourenço", "Castro", "Figueiredo",
              "Azevedo", "Freitas"],
    "pl_PL": ["Nowak", "Kowalski", "Wiśniewski", "Wójcik", "Kowalczyk", "Kamiński", "Lewandowski", "Zieliński",
              "Szymański", "Woźniak", "Dąbrowski", "Kozłowski", "Jankowski", "Mazur", "Wojciechowski",
              "Kwiatkowski", "Krawczyk", "Kaczmarek", "Piotrowski", "Grabowski", "Zając", "Pawłowski", "Michalski",
              "Król", "Wieczorek", "Jabłoński", "Wróbel", "Nowakowski", "Majewski", "Olszewski", "Stępień",
              "Malinowski", "Jaworski", "Adamczyk", "Dudek", "Nowicki", "Pawlak", "Górski", "Witkowski", "Sikora"],
}

STREETS = {
    "en_US": ["Oak Street", "Maple Avenue", "Cedar Lane", "Pine Street", "Elm Street", "Washington Avenue",
              "Park Avenue", "Lakeview Drive", "Highland Avenue", "Willow Court", "Ridge Road", "Hillcrest Drive",
              "Main Street", "Church Street", "Jefferson Street", "Lincoln Avenue", "Meadow Lane", "Forest Drive",
              "Spring Street", "Walnut Street", "Chestnut Street", "Magnolia Boulevard", "Sycamore Way",
              "Riverside Drive"],
    "en_GB": ["High Street", "Station Road", "Church Lane", "Victoria Road", "Park Road", "Manor Way", "Mill Lane",
              "The Crescent", "Kings Road", "Queens Avenue", "Elm Grove", "Albert Street", "Castle Street",
              "Orchard Close", "Springfield Road", "York Road", "Grange Road", "Windsor Gardens", "Chapel Street",
              "Beech Drive", "Mulberry Close", "Harbour View"],
    "it_IT": ["Via Roma", "Via Garibaldi", "Via Mazzini", "Corso Vittorio Emanuele II", "Via Dante Alighieri",
              "Via Cavour", "Viale della Repubblica", "Via XX Settembre", "Piazza della Libertà", "Via Giuseppe Verdi",
              "Via dei Mille", "Via Nazionale", "Corso Italia", "Via San Francesco", "Via delle Rose",
              "Via Leonardo da Vinci", "Via Manzoni", "Via Trieste", "Via dei Tigli", "Via Sant'Ambrogio",
              "Viale Monte Grappa", "Via del Pratello"],
    "de_DE": ["Hauptstraße", "Bahnhofstraße", "Gartenstraße", "Schulstraße", "Dorfstraße", "Bergstraße",
              "Lindenstraße", "Birkenweg", "Kirchstraße", "Waldstraße", "Ringstraße", "Mühlenweg", "Goethestraße",
              "Schillerstraße", "Am Markt", "Rosenweg", "Friedrichstraße", "Kastanienallee", "Brunnenstraße",
              "Feldstraße", "Uhlandstraße", "Am Lindenhof"],
    "fr_FR": ["rue de la République", "rue Victor Hugo", "avenue Jean Jaurès", "boulevard Voltaire", "rue Pasteur",
              "rue des Lilas", "place de la Mairie", "rue du Moulin", "allée des Tilleuls", "rue Nationale",
              "avenue de la Gare", "rue de l'Église", "chemin des Vignes", "rue Gambetta", "boulevard Saint-Michel",
              "rue Émile Zola", "impasse des Acacias", "rue du Général de Gaulle", "quai de la Loire",
              "rue Lafayette", "rue des Écoles", "avenue Foch"],
    "es_ES": ["Calle Mayor", "Calle Real", "Avenida de la Constitución", "Calle de Alcalá", "Gran Vía",
              "Calle del Sol", "Paseo de la Castellana", "Calle San Juan", "Plaza de España", "Calle Nueva",
              "Avenida de Andalucía", "Calle de Toledo", "Calle Cervantes", "Ronda de Valencia", "Calle de la Paz",
              "Calle Goya", "Avenida Diagonal", "Calle Princesa", "Calle Velázquez", "Calle de la Iglesia",
              "Carrer de Balmes", "Calle Larios"],
    "nl_NL": ["Kerkstraat", "Dorpsstraat", "Schoolstraat", "Molenweg", "Stationsweg", "Julianastraat",
              "Beatrixstraat", "Wilhelminastraat", "Nieuwstraat", "Markt", "Kastanjelaan", "Eikenlaan", "Parallelweg",
              "Prinsengracht", "Herengracht", "Keizersgracht", "Lindenlaan", "Hoofdstraat", "Industrieweg",
              "Sportlaan", "Oudegracht", "Vondelstraat"],
    "pt_PT": ["Rua da Liberdade", "Avenida da República", "Rua Augusta", "Rua de Santa Catarina", "Rua do Comércio",
              "Avenida dos Aliados", "Rua das Flores", "Travessa do Carmo", "Rua Direita", "Largo do Rato",
              "Rua da Prata", "Avenida de Roma", "Rua do Ouro", "Rua de Cedofeita", "Rua Miguel Bombarda",
              "Rua Garrett", "Rua do Almada", "Avenida da Boavista", "Rua Formosa", "Rua do Salitre"],
    "pl_PL": ["ul. Lipowa", "ul. Polna", "ul. Leśna", "ul. Słoneczna", "ul. Krótka", "ul. Szkolna", "ul. Ogrodowa",
              "ul. Kwiatowa", "ul. Mickiewicza", "ul. Kościuszki", "ul. Sienkiewicza", "ul. Długa",
              "ul. Marszałkowska", "al. Jerozolimskie", "ul. Piłsudskiego", "ul. Wolności", "ul. Kolejowa",
              "ul. Brzozowa", "ul. Spacerowa", "ul. Zielona"],
}

# city, postcode (lo, hi) or outward codes, lat, lon, landline prefix, plate code / region
CITIES = {
    "en_US": [
        ("Austin", "TX", (78701, 78759), 30.2672, -97.7431, ["512", "737"]),
        ("Seattle", "WA", (98101, 98199), 47.6062, -122.3321, ["206"]),
        ("Denver", "CO", (80202, 80239), 39.7392, -104.9903, ["303", "720"]),
        ("Portland", "OR", (97201, 97239), 45.5152, -122.6784, ["503", "971"]),
        ("Chicago", "IL", (60601, 60661), 41.8781, -87.6298, ["312", "773"]),
        ("Boston", "MA", (2108, 2137), 42.3601, -71.0589, ["617", "857"]),
        ("Atlanta", "GA", (30303, 30363), 33.7490, -84.3880, ["404", "678"]),
        ("Minneapolis", "MN", (55401, 55488), 44.9778, -93.2650, ["612"]),
        ("Raleigh", "NC", (27601, 27617), 35.7796, -78.6382, ["919", "984"]),
        ("Columbus", "OH", (43201, 43240), 39.9612, -82.9988, ["614"]),
        ("Phoenix", "AZ", (85003, 85054), 33.4484, -112.0740, ["602", "480"]),
        ("San Diego", "CA", (92101, 92199), 32.7157, -117.1611, ["619", "858"]),
        ("Nashville", "TN", (37201, 37250), 36.1627, -86.7816, ["615"]),
        ("Pittsburgh", "PA", (15201, 15244), 40.4406, -79.9959, ["412"]),
    ],
    "en_GB": [
        ("London", ["E1", "E14", "N1", "N7", "NW1", "NW3", "SE1", "SE15", "SW4", "SW11", "W2", "W12", "EC1V", "WC1H"],
         51.5074, -0.1278, "020"),
        ("Manchester", ["M1", "M4", "M14", "M20", "M21"], 53.4808, -2.2426, "0161"),
        ("Birmingham", ["B1", "B5", "B13", "B15", "B29"], 52.4862, -1.8904, "0121"),
        ("Leeds", ["LS1", "LS2", "LS6", "LS8", "LS17"], 53.8008, -1.5491, "0113"),
        ("Bristol", ["BS1", "BS3", "BS6", "BS7", "BS8"], 51.4545, -2.5879, "0117"),
        ("Edinburgh", ["EH1", "EH3", "EH6", "EH9", "EH10"], 55.9533, -3.1883, "0131"),
        ("Glasgow", ["G1", "G3", "G11", "G12", "G41"], 55.8642, -4.2518, "0141"),
        ("Cardiff", ["CF10", "CF11", "CF14", "CF24"], 51.4816, -3.1791, "029"),
        ("Sheffield", ["S1", "S7", "S10", "S11"], 53.3811, -1.4701, "0114"),
        ("Nottingham", ["NG1", "NG2", "NG5", "NG7"], 52.9548, -1.1581, "0115"),
        ("Brighton", ["BN1", "BN2", "BN3"], 50.8225, -0.1372, "01273"),
        ("Oxford", ["OX1", "OX2", "OX3", "OX4"], 51.7520, -1.2577, "01865"),
    ],
    "it_IT": [
        ("Milano", "MI", (20121, 20162), 45.4642, 9.1900, "02", "F205"),
        ("Roma", "RM", (118, 199), 41.9028, 12.4964, "06", "H501"),
        ("Torino", "TO", (10121, 10156), 45.0703, 7.6869, "011", "L219"),
        ("Napoli", "NA", (80121, 80147), 40.8518, 14.2681, "081", "F839"),
        ("Bologna", "BO", (40121, 40141), 44.4949, 11.3426, "051", "A944"),
        ("Firenze", "FI", (50121, 50145), 43.7696, 11.2558, "055", "D612"),
        ("Genova", "GE", (16121, 16167), 44.4056, 8.9463, "010", "D969"),
        ("Verona", "VR", (37121, 37142), 45.4384, 10.9916, "045", "L781"),
        ("Padova", "PD", (35121, 35143), 45.4064, 11.8768, "049", "G224"),
        ("Bari", "BA", (70121, 70132), 41.1171, 16.8719, "080", "A662"),
        ("Palermo", "PA", (90121, 90151), 38.1157, 13.3615, "091", "G273"),
        ("Trento", "TN", (38121, 38123), 46.0748, 11.1217, "0461", "L378"),
        ("Bergamo", "BG", (24121, 24129), 45.6983, 9.6773, "035", "A794"),
        ("Brescia", "BS", (25121, 25136), 45.5416, 10.2118, "030", "B157"),
    ],
    "de_DE": [
        ("Berlin", "B", (10115, 14199), 52.5200, 13.4050, "030"),
        ("München", "M", (80331, 81929), 48.1351, 11.5820, "089"),
        ("Hamburg", "HH", (20095, 22769), 53.5511, 9.9937, "040"),
        ("Köln", "K", (50667, 51149), 50.9375, 6.9603, "0221"),
        ("Frankfurt am Main", "F", (60306, 60599), 50.1109, 8.6821, "069"),
        ("Stuttgart", "S", (70173, 70629), 48.7758, 9.1829, "0711"),
        ("Düsseldorf", "D", (40210, 40629), 51.2277, 6.7735, "0211"),
        ("Leipzig", "L", (4103, 4357), 51.3397, 12.3731, "0341"),
        ("Dresden", "DD", (1067, 1328), 51.0504, 13.7373, "0351"),
        ("Nürnberg", "N", (90402, 90491), 49.4521, 11.0767, "0911"),
        ("Bremen", "HB", (28195, 28779), 53.0793, 8.8017, "0421"),
        ("Hannover", "H", (30159, 30669), 52.3759, 9.7320, "0511"),
        ("Freiburg im Breisgau", "FR", (79098, 79117), 47.9990, 7.8421, "0761"),
        ("Münster", "MS", (48143, 48167), 51.9607, 7.6261, "0251"),
    ],
    "fr_FR": [
        ("Paris", "75", (75001, 75020), 48.8566, 2.3522, "01"),
        ("Lyon", "69", (69001, 69009), 45.7640, 4.8357, "04"),
        ("Marseille", "13", (13001, 13016), 43.2965, 5.3698, "04"),
        ("Toulouse", "31", (31000, 31500), 43.6047, 1.4442, "05"),
        ("Nantes", "44", (44000, 44300), 47.2184, -1.5536, "02"),
        ("Bordeaux", "33", (33000, 33800), 44.8378, -0.5792, "05"),
        ("Lille", "59", (59000, 59800), 50.6292, 3.0573, "03"),
        ("Strasbourg", "67", (67000, 67200), 48.5734, 7.7521, "03"),
        ("Montpellier", "34", (34000, 34090), 43.6108, 3.8767, "04"),
        ("Rennes", "35", (35000, 35700), 48.1173, -1.6778, "02"),
        ("Nice", "06", (6000, 6300), 43.7102, 7.2620, "04"),
        ("Grenoble", "38", (38000, 38100), 45.1885, 5.7245, "04"),
    ],
    "es_ES": [
        ("Madrid", "M", (28001, 28055), 40.4168, -3.7038, "91"),
        ("Barcelona", "B", (8001, 8042), 41.3874, 2.1686, "93"),
        ("Valencia", "V", (46001, 46026), 39.4699, -0.3763, "96"),
        ("Sevilla", "SE", (41001, 41020), 37.3891, -5.9845, "95"),
        ("Zaragoza", "Z", (50001, 50021), 41.6488, -0.8891, "976"),
        ("Málaga", "MA", (29001, 29018), 36.7213, -4.4214, "95"),
        ("Bilbao", "BI", (48001, 48015), 43.2630, -2.9350, "94"),
        ("Valladolid", "VA", (47001, 47016), 41.6523, -4.7245, "983"),
        ("Granada", "GR", (18001, 18015), 37.1773, -3.5986, "958"),
        ("Alicante", "A", (3001, 3016), 38.3452, -0.4810, "96"),
    ],
    "nl_NL": [
        ("Amsterdam", "NH", (1011, 1109), 52.3676, 4.9041, "020"),
        ("Rotterdam", "ZH", (3011, 3089), 51.9244, 4.4777, "010"),
        ("Utrecht", "UT", (3511, 3585), 52.0907, 5.1214, "030"),
        ("Den Haag", "ZH", (2491, 2599), 52.0705, 4.3007, "070"),
        ("Eindhoven", "NB", (5611, 5658), 51.4416, 5.4697, "040"),
        ("Groningen", "GR", (9711, 9747), 53.2194, 6.5665, "050"),
        ("Haarlem", "NH", (2011, 2037), 52.3874, 4.6462, "023"),
        ("Nijmegen", "GE", (6511, 6546), 51.8126, 5.8372, "024"),
        ("Leiden", "ZH", (2311, 2334), 52.1601, 4.4970, "071"),
        ("Delft", "ZH", (2611, 2629), 52.0116, 4.3571, "015"),
    ],
    "pt_PT": [
        ("Lisboa", "LX", (1000, 1990), 38.7223, -9.1393, "21"),
        ("Porto", "PO", (4000, 4369), 41.1579, -8.6291, "22"),
        ("Braga", "BR", (4700, 4719), 41.5454, -8.4265, "253"),
        ("Coimbra", "CO", (3000, 3049), 40.2033, -8.4103, "239"),
        ("Aveiro", "AV", (3800, 3814), 40.6405, -8.6538, "234"),
        ("Faro", "FA", (8000, 8009), 37.0194, -7.9322, "289"),
        ("Setúbal", "SE", (2900, 2914), 38.5244, -8.8882, "265"),
        ("Funchal", "MA", (9000, 9064), 32.6669, -16.9241, "291"),
    ],
    "pl_PL": [
        ("Warszawa", "WA", (0, 4), 52.2297, 21.0122, "22"),
        ("Kraków", "KR", (30, 31), 50.0647, 19.9450, "12"),
        ("Wrocław", "DW", (50, 54), 51.1079, 17.0385, "71"),
        ("Poznań", "PO", (60, 61), 52.4064, 16.9252, "61"),
        ("Gdańsk", "GD", (80, 80), 54.3520, 18.6466, "58"),
        ("Łódź", "EL", (90, 94), 51.7592, 19.4560, "42"),
        ("Szczecin", "ZS", (70, 71), 53.4285, 14.5528, "91"),
        ("Lublin", "LU", (20, 20), 51.2465, 22.5684, "81"),
        ("Katowice", "SK", (40, 40), 50.2649, 19.0238, "32"),
    ],
}

COUNTRY_OF = {"en_US": "US", "en_GB": "GB", "it_IT": "IT", "de_DE": "DE", "fr_FR": "FR", "es_ES": "ES",
              "nl_NL": "NL", "pt_PT": "PT", "pl_PL": "PL"}
COUNTRY_NAME = {"US": "United States", "GB": "United Kingdom", "IT": "Italia", "DE": "Deutschland",
                "FR": "France", "ES": "España", "NL": "Nederland", "PT": "Portugal", "PL": "Polska"}

# Personal mailbox providers (public services; addresses built on them are personal data)
MAIL_PROVIDERS = {
    "en_US": ["gmail.com", "outlook.com", "yahoo.com", "icloud.com", "proton.me"],
    "en_GB": ["gmail.com", "outlook.com", "btinternet.com", "hotmail.co.uk", "icloud.com"],
    "it_IT": ["gmail.com", "libero.it", "virgilio.it", "outlook.it", "tiscali.it"],
    "de_DE": ["gmail.com", "gmx.de", "web.de", "t-online.de", "posteo.de"],
    "fr_FR": ["gmail.com", "orange.fr", "free.fr", "laposte.net", "outlook.fr"],
    "es_ES": ["gmail.com", "hotmail.es", "yahoo.es", "outlook.es", "telefonica.net"],
    "nl_NL": ["gmail.com", "ziggo.nl", "kpnmail.nl", "outlook.com", "hotmail.nl"],
    "pt_PT": ["gmail.com", "sapo.pt", "outlook.pt", "hotmail.com", "clix.pt"],
    "pl_PL": ["gmail.com", "wp.pl", "onet.pl", "interia.pl", "o2.pl"],
}

# Fictional employers invented for this generator (name, domain, home locale).
COMPANIES = [
    ("Brightwater Logistics", "brightwater-logistics.com", "en_US"),
    ("Kestrel Analytics", "kestrel-analytics.io", "en_GB"),
    ("Nordlicht Energie GmbH", "nordlicht-energie.de", "de_DE"),
    ("Fratelli Marchesi S.r.l.", "fratellimarchesi.it", "it_IT"),
    ("Atelier Lumière SAS", "atelier-lumiere.fr", "fr_FR"),
    ("Ortega & Vidal Asesores", "ortegavidal-asesores.es", "es_ES"),
    ("Polderwerk BV", "polderwerk-bv.nl", "nl_NL"),
    ("Tidewell Health", "tidewellhealth.com", "en_US"),
    ("Quillfeather Books", "quillfeather-books.co.uk", "en_GB"),
    ("Vela Pagamenti", "velapagamenti.it", "it_IT"),
    ("Hafenblick Versicherung AG", "hafenblick-vers.de", "de_DE"),
    ("Marlowe & Finch Legal", "marlowefinch-legal.co.uk", "en_GB"),
    ("Sunpeak Solar", "sunpeak-solar.com", "en_US"),
    ("Cobaltline Telecom", "cobaltline-tel.net", "fr_FR"),
    ("Granja Azul Alimentos", "granjaazul-alimentos.pt", "pt_PT"),
    ("Wislaware sp. z o.o.", "wislaware.pl", "pl_PL"),
    ("Lumen Pharmacy Group", "lumenpharmacy-group.eu", "nl_NL"),
    ("Corvid Mobility", "corvidmobility.io", "de_DE"),
    ("Meridian Dental Clinics", "meridian-dental.co.uk", "en_GB"),
    ("Alpenrose Hotels", "alpenrose-hotels.eu", "de_DE"),
    ("Cantiere Navale Lucchesi", "cnlucchesi.it", "it_IT"),
    ("Mistral Assurances", "mistral-assurances.fr", "fr_FR"),
    ("Pradera Movilidad", "pradera-movilidad.es", "es_ES"),
    ("Harbourlight Retail", "harbourlight-retail.com", "en_GB"),
]

PROJECTS = ["orders-service", "billing-api", "customer-portal", "payroll-sync", "fleet-tracker", "claims-engine",
            "booking-app", "crm-import", "notification-worker", "kyc-gateway", "warehouse-ui", "patient-scheduler",
            "data-pipeline", "auth-service", "invoice-generator", "mobile-backend", "analytics-etl",
            "support-dashboard", "telemetry-ingest", "hr-portal", "loyalty-points", "shipment-api",
            "tenant-admin", "checkout-web", "ledger-core", "reporting-jobs", "partner-sync", "device-registry"]

HOSTS = ["web-01", "web-02", "api-prod-2", "db-primary", "db-replica-1", "worker-3", "build-agent-7", "bastion",
         "edge-fra1-04", "k8s-node-12", "cache-01", "ingest-02", "mail-relay", "vpn-gw", "app-blue",
         "app-green", "batch-runner", "metrics-1", "queue-02", "staging-api"]

PASSWORD_WORDS = ["Falcon", "Marmalade", "Copper", "Lantern", "Biscotto", "Kaffee", "Orchid", "Glacier",
                  "Pinecone", "Velvet", "Thunder", "Mango", "Saffron", "Harbor", "Quartz", "Nebula", "Pistachio",
                  "Walnut", "Zephyr", "Cobalt", "Tramonto", "Eichhorn", "Papillon", "Girasole", "Moonbeam",
                  "Sputnik", "Rhubarb", "Kiwi", "Lavanda", "Brezel"]

PUBLIC_ENTITIES = {
    "db": ["PostgreSQL", "MySQL", "Redis", "MongoDB", "Elasticsearch", "SQLite", "MariaDB", "Cassandra",
           "ClickHouse"],
    "infra": ["Docker", "Kubernetes", "Terraform", "Ansible", "nginx", "HAProxy", "Traefik", "Helm", "Vault",
              "Consul", "systemd", "OpenSSL", "Let's Encrypt", "Caddy"],
    "saas": ["GitHub", "GitLab", "Bitbucket", "Jenkins", "CircleCI", "Stripe", "PayPal", "Adyen", "Twilio",
             "SendGrid", "Mailgun", "Slack", "Sentry", "Datadog", "Grafana", "Prometheus", "PagerDuty", "Jira",
             "Cloudflare", "Heroku", "DigitalOcean", "Fastly", "Auth0", "Okta", "Mapbox", "OpenStreetMap"],
    "cloud": ["AWS", "Amazon S3", "Amazon RDS", "Google Cloud", "BigQuery", "Microsoft Azure", "Azure Blob Storage",
              "AWS Lambda", "Amazon SES"],
    "lib": ["React", "Vue", "Angular", "Django", "Flask", "FastAPI", "Express", "Spring Boot", "Rails", "Laravel",
            "pandas", "NumPy", "SQLAlchemy", "Hibernate", "Jest", "pytest", "JUnit", "Celery", "Gunicorn",
            "uvicorn", "Prisma", "Sequelize", "axios", "Pydantic", "Alembic", "Flyway", "Liquibase", "tokio",
            "serde", "gRPC", "Kafka", "RabbitMQ"],
    "lang": ["Node.js", "Python", "Go", "Rust", "Java", "TypeScript", "Kotlin", "PHP", "Ruby", ".NET"],
    "org": ["Mozilla", "Apache Software Foundation", "Linux Foundation", "Python Software Foundation",
            "Cloud Native Computing Foundation", "OpenJS Foundation", "Eclipse Foundation", "Ubuntu", "Debian",
            "Alpine Linux", "Red Hat", "Visa", "Mastercard", "American Express", "SWIFT", "Apple", "Google",
            "Microsoft", "Samsung", "Bosch", "Volkswagen", "Fiat", "Renault", "Toyota", "Tesla"],
}

PUBLIC_FIGURES = ["Linus Torvalds", "Guido van Rossum", "Ryan Dahl", "Brendan Eich", "James Gosling",
                  "Bjarne Stroustrup", "Yukihiro Matsumoto", "Rasmus Lerdorf", "Larry Wall", "Dennis Ritchie",
                  "Ken Thompson", "Rob Pike", "Brian Kernighan", "Donald Knuth", "Tim Berners-Lee",
                  "Grace Hopper", "Ada Lovelace", "Alan Turing", "Richard Stallman", "Martin Fowler", "Kent Beck",
                  "Robert C. Martin", "Edsger Dijkstra", "Leslie Lamport", "Barbara Liskov", "Margaret Hamilton",
                  "Salvatore Sanfilippo", "David Heinemeier Hansson", "Taylor Otwell", "Evan You",
                  "Mitchell Hashimoto", "Solomon Hykes", "Anders Hejlsberg"]

PUBLIC_URLS = {
    "docs": [
        "https://docs.python.org/3/library/datetime.html", "https://docs.python.org/3/library/logging.html",
        "https://nodejs.org/api/crypto.html", "https://nodejs.org/api/fs.html",
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie",
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        "https://www.postgresql.org/docs/16/sql-createindex.html",
        "https://www.postgresql.org/docs/current/runtime-config-logging.html",
        "https://kubernetes.io/docs/concepts/configuration/secret/",
        "https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/",
        "https://docs.docker.com/compose/compose-file/", "https://docs.docker.com/build/building/secrets/",
        "https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions",
        "https://docs.stripe.com/webhooks", "https://www.rfc-editor.org/rfc/rfc7519",
        "https://datatracker.ietf.org/doc/html/rfc6749", "https://go.dev/doc/effective_go",
        "https://doc.rust-lang.org/book/ch09-00-error-handling.html",
        "https://docs.djangoproject.com/en/5.0/ref/settings/", "https://flask.palletsprojects.com/en/3.0.x/config/",
        "https://fastapi.tiangolo.com/tutorial/security/", "https://spring.io/guides/gs/rest-service/",
        "https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-test", "https://redis.io/docs/latest/commands/scan/",
        "https://nginx.org/en/docs/http/ngx_http_log_module.html", "https://www.terraform.io/docs/language/values/variables.html",
        "https://docs.ansible.com/ansible/latest/vault_guide/index.html", "https://jestjs.io/docs/snapshot-testing",
        "https://docs.pytest.org/en/stable/how-to/fixtures.html", "https://git-scm.com/docs/git-blame",
        "https://git-scm.com/docs/git-filter-branch", "https://www.freedesktop.org/software/systemd/man/journalctl.html",
        "https://laravel.com/docs/11.x/configuration", "https://guides.rubyonrails.org/testing.html",
        "https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html",
        "https://graphql.org/learn/queries/", "https://owasp.org/www-community/attacks/Session_hijacking_attack",
        "https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html",
        "https://gdpr-info.eu/art-17-gdpr/", "https://www.iso.org/standard/81090.html",
    ],
    "registry": [
        "https://registry.npmjs.org/", "https://pypi.org/simple/", "https://repo1.maven.org/maven2/",
        "https://proxy.golang.org", "https://index.crates.io/", "https://rubygems.org/",
        "https://hub.docker.com/_/postgres", "https://deb.debian.org/debian", "http://archive.ubuntu.com/ubuntu",
        "https://dl-cdn.alpinelinux.org/alpine/v3.19/main", "https://api.nuget.org/v3/index.json",
        "https://repo.packagist.org", "https://ghcr.io/v2/", "https://registry-1.docker.io/v2/",
    ],
    "repo": [
        "https://github.com/psf/requests", "https://github.com/pallets/flask", "https://github.com/expressjs/express",
        "https://github.com/golang/go", "https://github.com/kubernetes/kubernetes", "https://github.com/rust-lang/rust",
        "https://github.com/django/django", "https://github.com/nodejs/node", "https://github.com/redis/redis",
        "https://github.com/postgres/postgres", "https://github.com/facebook/react", "https://github.com/vuejs/core",
        "https://github.com/spring-projects/spring-boot", "https://github.com/laravel/framework",
        "https://github.com/rails/rails", "https://github.com/tokio-rs/tokio", "https://github.com/hashicorp/terraform",
        "https://gitlab.com/gitlab-org/gitlab", "https://github.com/grafana/grafana", "https://github.com/curl/curl",
    ],
    "cdn": [
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap",
        "https://code.jquery.com/jquery-3.7.1.min.js",
    ],
    "badge": [
        "https://img.shields.io/badge/license-MIT-blue.svg", "https://img.shields.io/badge/python-3.12-blue",
        "https://img.shields.io/badge/code%20style-black-000000.svg", "https://img.shields.io/badge/node-%3E%3D20-brightgreen",
        "https://img.shields.io/badge/PRs-welcome-brightgreen.svg",
    ],
    "license": [
        "https://www.apache.org/licenses/LICENSE-2.0", "https://opensource.org/licenses/MIT",
        "https://opensource.org/licenses/BSD-3-Clause", "https://semver.org/", "https://keepachangelog.com/en/1.1.0/",
        "https://www.conventionalcommits.org/en/v1.0.0/", "https://json-schema.org/draft/2020-12/schema",
        "http://www.w3.org/2001/XMLSchema-instance", "https://maven.apache.org/xsd/maven-4.0.0.xsd",
    ],
}

# Vehicle manufacturer identifiers (public WMI assignments) used to start VINs
WMIS = ["WVW", "WBA", "WDD", "WAU", "ZFA", "ZAR", "VF1", "VF3", "VF7", "VSS", "TMB", "YV1", "SAL", "SAJ",
        "1HG", "1FA", "2HG", "3VW", "5YJ", "JHM", "JTD", "KMH", "KNA", "SB1", "NMT"]
VIN_YEARS = "HJKLMNPRST"  # 2017..2026

# Placeholder person names that are conventionally used as examples
PLACEHOLDER_PEOPLE = [("John", "Doe"), ("Jane", "Doe"), ("Max", "Mustermann"), ("Erika", "Mustermann"),
                      ("Mario", "Rossi"), ("Jean", "Dupont"), ("Test", "User"), ("Demo", "Account"),
                      ("Example", "Person"), ("Fulano", "de Tal")]
